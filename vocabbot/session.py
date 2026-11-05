"""One Chrome window working through Vocabulary.com assignments.

Each Session runs in its own thread with its own browser and profile. Sessions share the
Store (answer cache) and the Answerer (OpenAI client), both of which are thread-safe.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import openai
from selenium.common.exceptions import NoSuchWindowException, StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement

from . import browser
from .answerer import Answerer
from .config import Config
from .store import Store

START_URL = "https://www.vocabulary.com/account/activities/"

# Page selectors (Vocabulary.com markup)
SEL_QUESTION = ".question"
SEL_CHOICES = ".choices a"
SEL_INSTRUCTIONS = ".instructions"
SEL_SENTENCE = ".sentence"
SEL_AUDIO_BUTTON = "button.playword.ss-highvolume"
SEL_SPELLING_INPUT = "input.wordspelling"
SEL_SPELLING_WORD = "div.sentence.complete strong"
SEL_NEXT = "button.next.active[aria-label='Next question']"
SEL_WRONG = ".wrong"
SEL_ACHIEVEMENT = ".hero.with-header-padding"
SEL_ROUND_COMPLETE = "h1 svg.progress-icon"
SEL_FINISHED = ".practiceComplete.activity-summary"
SEL_BLOCKER = "div.blocker"
SEL_COUNTDOWN = "div.blocker .countdown"

# Vocabulary.com caches the signed-in user in localStorage["me/auth"]; read just the name.
_ACCOUNT_NAME_JS = """
try {
  const raw = localStorage.getItem('me/auth');
  if (!raw) return null;
  const auth = ((JSON.parse(raw) || {}).value || {}).auth || {};
  return auth.loggedin ? (auth.fullname || auth.nickname || null) : null;
} catch (e) { return null; }
"""
NAME_REFRESH = 60.0         # seconds between re-reading the signed-in name once known
NAME_REFRESH_UNKNOWN = 5.0  # ...and while waiting for the user to sign in

STUCK_AFTER = 25.0     # seconds on one question with no progress before reloading the page
RESULT_TIMEOUT = 4.0   # seconds to wait for the page to mark an answer right or wrong


@dataclass
class Question:
    element: WebElement
    kind: str                      # "choice" | "image" | "spelling"
    text: str = ""
    choices: list[str] = field(default_factory=list)
    links: list[WebElement] = field(default_factory=list)

    @property
    def ident(self) -> tuple[str, str]:
        return (self.element.id, self.text)


@dataclass
class SessionStatus:
    """What the dashboard shows. Written by the session thread, read by the UI thread."""
    name: str
    account: str = ""              # signed-in Vocabulary.com name, once known
    state: str = "starting"
    detail: str = ""
    correct: int = 0
    wrong: int = 0
    cache_hits: int = 0
    ai_calls: int = 0
    started: float = field(default_factory=time.monotonic)


class Session:
    def __init__(self, name: str, index: int, profile_dir: Path, config: Config,
                 store: Store, answerer: Answerer, stop: threading.Event):
        self.name = name
        self.index = index
        self.profile_dir = profile_dir
        self.config = config
        self.store = store
        self.answerer = answerer
        self.stop = stop
        self.status = SessionStatus(name)
        self.log = logging.getLogger(f"vocabbot.session.{name}")

        self._driver = None
        self._driver_lock = threading.Lock()
        self._current: tuple[str, str] | None = None   # ident of the question on screen
        self._current_since = 0.0
        self._answer_at = 0.0                 # monotonic time the next answer may be submitted
        self._last_answer: float | None = None
        self._current_done = False
        self._finished_seen = False
        self._name_checked = 0.0

    # ---- lifecycle -----------------------------------------------------

    def run(self) -> None:
        try:
            self._start_browser()
            if self.stop.is_set():
                return
            self._set("waiting", "Sign in and open an assignment in this window")

            while not self.stop.is_set():
                try:
                    self._tick()
                except StaleElementReferenceException:
                    continue  # the page re-rendered mid-read; read it again
                except NoSuchWindowException:
                    # The tab we were driving is gone (closed by hand, or replaced by Chrome).
                    if not self._recover_window():
                        self._set("closed", "Browser window was closed")
                        return
                except WebDriverException as e:
                    if not self._browser_alive():
                        self._set("closed", "Browser window was closed")
                        return
                    self.log.warning("WebDriver error: %s", (e.msg or str(e)).splitlines()[0])
                    self._sleep(1)
        except Exception as e:
            self.log.exception("Session crashed")
            self._set("error", (str(e).strip().splitlines() or [type(e).__name__])[0][:150])
        finally:
            self.close()
            if self.status.state not in ("error", "closed"):
                self._set("stopped", "")

    def _start_browser(self, attempts: int = 2) -> None:
        """Launch Chrome and open the start page. If the launch itself fails, retry once."""
        for attempt in range(1, attempts + 1):
            if self.stop.is_set():
                return
            self._set("launching", "Starting Chrome" + (f" (retry {attempt - 1})" if attempt > 1 else ""))
            try:
                driver = browser.launch(self.profile_dir, self.config.chrome_args, self.index)
                with self._driver_lock:
                    self._driver = driver
                if self.stop.is_set():
                    return  # run()'s finally quits it
                try:
                    driver.get(START_URL)
                except NoSuchWindowException:
                    if not self._recover_window():
                        raise
                return
            except WebDriverException:
                self.close()
                if attempt == attempts or self.stop.is_set():
                    raise
                self.log.warning("Chrome failed to start, retrying", exc_info=True)
                self._sleep(2)

    def _recover_window(self) -> bool:
        """Re-attach to a live tab. A freshly started Chrome sometimes swaps its first tab for a
        new-tab page, leaving the driver on a dead tab ("web view not found"); a user can also
        close the tab. Switches to the newest live tab and opens the start page if it is blank."""
        try:
            handles = self._d.window_handles
        except WebDriverException:
            return False
        for handle in reversed(handles):
            try:
                self._d.switch_to.window(handle)
                url = self._d.current_url
            except WebDriverException:
                continue
            self.log.info("Switched to a live tab (%s)", url[:60])
            if "vocabulary.com" not in url:
                self._d.get(START_URL)
                self._set("waiting", "Sign in and open an assignment in this window")
            return True
        return False

    def close(self) -> None:
        """Quit this session's browser only. Safe to call from any thread, more than once."""
        with self._driver_lock:
            driver, self._driver = self._driver, None
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                self.log.debug("driver.quit() failed", exc_info=True)

    # ---- main loop -----------------------------------------------------

    def _tick(self) -> None:
        self._refresh_account_name()
        if self._wait_out_blocker():
            return

        if self._exists(SEL_FINISHED):
            if not self._finished_seen:
                self._finished_seen = True
                self.log.info("Assignment complete")
                self._set("waiting", "Assignment complete - open another one")
            self._sleep(2)
            return
        self._finished_seen = False

        self._count_achievements()
        if self._click_next():
            self._sleep(1)
            return

        if not self._exists(SEL_QUESTION):
            self._current = None
            if self.status.state != "waiting":
                self._set("waiting", "Sign in and open an assignment in this window")
            self._sleep(1)
            return

        question = self._read_question()
        if question is None:          # still rendering
            self._sleep(0.5)
            return

        now = time.monotonic()
        if question.ident != self._current:
            self._current, self._current_since, self._current_done = question.ident, now, False
            # Pace answers min_wait..max_wait seconds after the previous one (or after this
            # question appeared, if there was a break), however long the page or AI took.
            recent = self._last_answer is not None and now - self._last_answer < 30
            self._schedule_next(self._last_answer if recent else now)

        if now - self._current_since > STUCK_AFTER:
            self._reload("No progress on this question")
            return
        if self._current_done:        # answered; waiting for the page to move on
            self._sleep(0.5)
            return

        handler = {"choice": self._answer_choice, "image": self._answer_image,
                   "spelling": self._answer_spelling}[question.kind]
        self._current_done = handler(question)
        if not self._current_done:
            self._sleep(0.5)

    # ---- reading the page ----------------------------------------------

    def _read_question(self) -> Question | None:
        containers = self._d.find_elements(By.CSS_SELECTOR, SEL_QUESTION)
        if not containers:
            return None
        el = containers[-1]  # older questions stay in the DOM; the newest is last
        classes = el.get_attribute("class") or ""
        links = el.find_elements(By.CSS_SELECTOR, SEL_CHOICES)

        if "typeI" in classes or "multiple-image" in classes or el.get_attribute("data-template") == "multiple-image":
            return Question(el, "image", links=links) if links else None

        if el.find_elements(By.CSS_SELECTOR, SEL_AUDIO_BUTTON) and el.find_elements(By.CSS_SELECTOR, SEL_SPELLING_INPUT):
            return Question(el, "spelling")

        choices = [link.text.strip() for link in links]
        if not choices or not all(choices):
            return None

        instructions = self._text(el, SEL_INSTRUCTIONS).replace("\n", " ")
        sentence = self._text(el, SEL_SENTENCE)
        text = f"{instructions}\nContext: {sentence}" if sentence else instructions
        return Question(el, "choice", text=text, choices=choices, links=links)

    # ---- answering -----------------------------------------------------

    def _answer_choice(self, q: Question) -> bool:
        self._set("answering", q.text.replace("\n", "  "))
        tried: set[int] = set()

        cached = self.store.lookup(q.text, q.choices)
        if cached is not None:
            outcome = self._try(q, cached)
            if outcome is None:
                return False
            if outcome:
                self._count("cache_hits")
                self._count("correct_answers")
                return True
            self.log.info("Cached answer was wrong, forgetting it: %s", q.choices[cached])
            self.store.forget(q.text, q.choices)
            self._count("wrong_answers")
            tried.add(cached)
        else:
            self._count("cache_misses")

        while len(tried) < len(q.choices) and not self.stop.is_set():
            remaining = [i for i in range(len(q.choices)) if i not in tried]
            index = remaining[0] if len(remaining) == 1 else self._ask_ai(q, tried)
            if index is None:
                index = remaining[0]
                self.log.info("No usable AI answer, guessing choice %d", index + 1)

            outcome = self._try(q, index)
            if outcome is None:
                return False
            if outcome:
                self.store.remember(q.text, q.choices, index)
                self._count("correct_answers")
                return True
            self._count("wrong_answers")
            tried.add(index)
        return False

    def _answer_image(self, q: Question) -> bool:
        self._set("answering", "Image question - trying each picture")
        for index in range(len(q.links)):
            outcome = self._try(q, index, pause=None if index == 0 else 0.5)
            if outcome is None:
                return False
            if outcome:
                self._count("correct_answers")
                return True
        return False

    def _answer_spelling(self, q: Question) -> bool:
        word_el = q.element.find_elements(By.CSS_SELECTOR, SEL_SPELLING_WORD)
        word = (word_el[0].get_attribute("innerText") or "").strip() if word_el else ""
        if not word:
            self.log.info("Spelling question without a visible word")
            return False
        self._set("answering", f"Spelling: {word}")
        if self._exists(SEL_NEXT):
            return False
        wrong_before = self._count_wrong()
        box = q.element.find_element(By.CSS_SELECTOR, SEL_SPELLING_INPUT)
        box.clear()
        self._wait_for_turn()
        box.send_keys(word + Keys.RETURN)
        self._answered()
        if self._await_result(wrong_before):
            self._count("correct_answers")
            return True
        return False

    def _ask_ai(self, q: Question, exclude: set[int]) -> int | None:
        self.status.ai_calls += 1
        try:
            return self.answerer.choose(q.text, q.choices, exclude)
        except openai.OpenAIError as e:
            self.log.warning("OpenAI request failed: %s", e)
            return None

    def _try(self, q: Question, index: int, pause: float | None = None) -> bool | None:
        """Click a choice. True = correct, False = wrong, None = couldn't tell (page changed / no response)."""
        if pause is None:
            self._wait_for_turn()
        else:
            self._sleep(pause)
        if self.stop.is_set():
            return None

        if self._exists(SEL_NEXT):
            return None  # already answered; the next tick clicks Next. Clicking now would "confirm" any pick.
        wrong_before = self._count_wrong()
        try:
            q.links[index].click()
        except WebDriverException as e:
            self.log.info("Could not click choice %d: %s", index + 1, (e.msg or str(e)).splitlines()[0])
            return None
        self._answered()
        label = q.choices[index] if q.choices else f"picture {index + 1}"
        self.log.info("Picked %r", label)
        return self._await_result(wrong_before)

    def _schedule_next(self, base: float) -> None:
        self._answer_at = base + random.uniform(self.config.min_wait, self.config.max_wait)

    def _wait_for_turn(self) -> None:
        self._sleep(max(0.0, self._answer_at - time.monotonic()))

    def _answered(self) -> None:
        """Record a submitted answer; a retry on the same question waits a fresh interval."""
        self._last_answer = time.monotonic()
        self._schedule_next(self._last_answer)

    def _await_result(self, wrong_before: int) -> bool | None:
        """Wait for the page to react. Compares the count of `.wrong` marks so that a
        wrong earlier attempt on the same question does not mask a correct retry."""
        deadline = time.monotonic() + RESULT_TIMEOUT
        while time.monotonic() < deadline and not self.stop.is_set():
            if self._count_wrong() > wrong_before:
                return False
            if self._exists(SEL_NEXT):
                return True
            self._sleep(0.2)
        return None

    # ---- interstitials -------------------------------------------------

    def _refresh_account_name(self) -> None:
        now = time.monotonic()
        interval = NAME_REFRESH if self.status.account else NAME_REFRESH_UNKNOWN
        if now - self._name_checked < interval:
            return
        self._name_checked = now
        try:
            name = self._d.execute_script(_ACCOUNT_NAME_JS)
        except WebDriverException:
            return
        name = name.strip()[:40] if isinstance(name, str) else ""
        if name and name != self.status.account:
            self.log.info("Signed in as %s", name)
            self.store.set_account_name(self.name, name)
        self.status.account = name

    def _wait_out_blocker(self) -> bool:
        if not self._exists(SEL_BLOCKER):
            return False
        countdown = self._d.find_elements(By.CSS_SELECTOR, SEL_COUNTDOWN)
        try:
            seconds = int(countdown[0].text.strip()) + 0.5
        except (IndexError, ValueError):
            seconds = random.uniform(self.config.min_wait, self.config.max_wait)
        self._set("blocked", f"Countdown on page, waiting {seconds:.0f}s")
        self._sleep(seconds)
        return True

    def _count_achievements(self) -> None:
        for el in self._d.find_elements(By.CSS_SELECTOR, SEL_ACHIEVEMENT):
            if not el.get_attribute("data-processed"):
                self._d.execute_script("arguments[0].setAttribute('data-processed', 'true');", el)
                self._count("achievements")
                self.log.info("Achievement unlocked")

    def _click_next(self) -> bool:
        buttons = self._d.find_elements(By.CSS_SELECTOR, SEL_NEXT)
        if not buttons:
            return False
        if self._exists(SEL_ROUND_COMPLETE):
            self.log.info("Round complete")
        try:
            buttons[0].click()
        except WebDriverException:
            return False  # not clickable yet (animating); try again next tick
        return True

    def _reload(self, reason: str) -> None:
        self.log.info("%s, reloading page", reason)
        self._set("reloading", reason)
        self._d.refresh()
        self._current = None
        self._sleep(random.uniform(self.config.min_wait, self.config.max_wait))

    # ---- helpers -------------------------------------------------------

    @property
    def _d(self):
        """The live driver; raises WebDriverException once close() has run (e.g. from another thread)."""
        driver = self._driver
        if driver is None:
            raise WebDriverException("browser is closed")
        return driver

    def _exists(self, selector: str) -> bool:
        return bool(self._d.find_elements(By.CSS_SELECTOR, selector))

    def _count_wrong(self) -> int:
        return len(self._d.find_elements(By.CSS_SELECTOR, SEL_WRONG))

    @staticmethod
    def _text(el: WebElement, selector: str) -> str:
        found = el.find_elements(By.CSS_SELECTOR, selector)
        return found[0].text.strip() if found else ""

    def _browser_alive(self) -> bool:
        try:
            return bool(self._driver and self._driver.window_handles)
        except Exception:
            return False

    def _sleep(self, seconds: float) -> None:
        self.stop.wait(seconds)  # returns early on Ctrl+C

    def _set(self, state: str, detail: str) -> None:
        self.status.state = state
        self.status.detail = detail

    _SESSION_FIELDS = {"correct_answers": "correct", "wrong_answers": "wrong", "cache_hits": "cache_hits"}

    def _count(self, counter: str) -> None:
        self.store.incr(counter)
        attr = self._SESSION_FIELDS.get(counter)
        if attr:
            setattr(self.status, attr, getattr(self.status, attr) + 1)
