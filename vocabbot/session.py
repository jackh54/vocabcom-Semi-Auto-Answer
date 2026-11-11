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

from . import assignments as assignment_list
from . import browser
from .answerer import Answerer
from .config import Config
from .store import Store, cache_key, normalize

START_URL = "https://www.vocabulary.com/account/activities/"
VOCABTRAINER_URL = "https://www.vocabulary.com/vocabtrainer/"

# Page selectors (Vocabulary.com markup)
# Practice pages use ".question"; VocabTrainer wraps the same question markup in ".box-question".
SEL_QUESTION = ".question, .box-question"
SEL_CHOICES = ".choices a"
SEL_INSTRUCTIONS = ".instructions"
SEL_SENTENCE = ".sentence"
SEL_AUDIO_BUTTON = "button.playword.ss-highvolume"
SEL_SPELLING_INPUT = "input.wordspelling"
SEL_SPELLING_WORD = "div.sentence.complete strong"
SEL_NEXT = "button.next.active[aria-label='Next question'], button.btn-next"
SEL_FEEDBACK = ".box-feedback-correct, .box-feedback-incorrect"   # VocabTrainer's verdict
SEL_SURRENDER = "button.surrender"                                 # spelling: reveal the answer
SEL_LOCKOUT = ".lockout-title"                                     # VocabTrainer "you're rushing" pause
SEL_LOCKOUT_TIMER = ".lockout-continue-text b"
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

ASSIGNMENTS_REFRESH = 60.0  # seconds between re-reading the assignment list while idle
BETWEEN_QUESTIONS = 10.0    # a gap with no question shorter than this is still the same assignment
RETURN_HOME_AFTER = 4.0     # seconds on the finished screen before going back to the assignments page
IDLE_STATES = ("waiting", "choosing", "done")

STUCK_AFTER = 25.0     # seconds on one question with no progress before reloading the page
RESULT_TIMEOUT = 6.0   # seconds to wait for the page to mark an answer right or wrong

# Outcomes of clicking a choice
RIGHT, WRONG, NO_RESULT, NOT_CLICKED = "right", "wrong", "no response", "not clicked"


@dataclass
class Question:
    element: WebElement
    kind: str                      # "choice" | "image" | "spelling"
    text: str = ""
    choices: list[str] = field(default_factory=list)
    links: list[WebElement] = field(default_factory=list)
    marked_wrong: set[int] = field(default_factory=set)   # choices the page already marked incorrect

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
    assignments_done: int = 0
    ai_calls: int = 0
    assignments: list = field(default_factory=list)   # unfinished assignments (dicts), soonest due first
    assignments_loaded: bool = False
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
        self.start_url = START_URL
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
        self._assignments_checked = 0.0
        self._assignments_dirty = True
        self._last_question_at = 0.0
        self._opened_at = 0.0
        self._return_home_at: float | None = None
        self._open_request: tuple[str, str] | None = None  # (url, name) chosen from the app or CLI
        self._request_lock = threading.Lock()
        self._failed: dict[str, set[str]] = {}  # cache key -> normalized choices that failed

    # ---- lifecycle -----------------------------------------------------

    def run(self) -> None:
        try:
            self._start_browser()
            if self.stop.is_set():
                return
            self._set("waiting", "Sign in to Vocabulary.com in this window")

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
                    driver.get(self.start_url)
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
                self._d.get(self.start_url)
                self._set("waiting", "Sign in to Vocabulary.com in this window")
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
        if self._open_requested():
            return
        if self._wait_out_lockout():
            return
        if self._wait_out_blocker():
            return

        if self._exists(SEL_FINISHED):
            if not self._finished_seen:
                self._finished_seen = True
                self._assignments_dirty = True
                self.status.assignments_done += 1
                self.log.info("Assignment complete (%d this run)", self.status.assignments_done)
                self._set("done", "Assignment complete - choose the next one")
                self._return_home_at = time.monotonic() + RETURN_HOME_AFTER
            if self._return_home_at and time.monotonic() >= self._return_home_at:
                self._return_home_at = None
                self._d.get(self.start_url)  # its assignments page has the live list
            self._sleep(1)
            return

        self._count_achievements()
        if self._click_next():
            self._sleep(1)
            return

        if not self._exists(SEL_QUESTION):
            self._current = None
            busy_since = max(self._last_question_at, self._opened_at)
            in_assignment = self.status.state in ("answering", "opening", "reloading", "paused")
            if in_assignment and time.monotonic() - busy_since < BETWEEN_QUESTIONS:
                self._sleep(0.5)  # between questions, or the assignment is still loading
                return
            self._refresh_assignments()
            self._show_idle_state()
            self._sleep(1)
            return

        question = self._read_question()
        if question is None:          # still rendering
            self._sleep(0.5)
            return
        self._last_question_at = time.monotonic()
        self._return_home_at = None

        now = time.monotonic()
        if question.ident != self._current:
            self._current, self._current_since, self._current_done = question.ident, now, False
            self._finished_seen = False  # a new question means a new (or resumed) assignment
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
        # Choices the site has already marked wrong (they stop accepting clicks), e.g. from
        # an earlier attempt before a reload.
        marked = {i for i, link in enumerate(links) if "incorrect" in (link.get_attribute("class") or "").split()}

        is_image = ("typeI" in classes or "multiple-image" in classes or "type-image" in classes.split()
                    or el.get_attribute("data-template") == "multiple-image")
        if is_image:
            if not links:
                return None
            # The prompt identifies the question across VocabTrainer's redraws (images have no text).
            prompt = self._text(el, SEL_INSTRUCTIONS).replace("\n", " ")
            return Question(el, "image", text=prompt, links=links, marked_wrong=marked)

        if el.find_elements(By.CSS_SELECTOR, SEL_SPELLING_INPUT):
            return Question(el, "spelling")

        choices = [link.text.strip() for link in links]
        if not choices or not all(choices):
            return None

        instructions = self._text(el, SEL_INSTRUCTIONS).replace("\n", " ")
        sentence = self._text(el, SEL_SENTENCE)
        text = f"{instructions}\nContext: {sentence}" if sentence else instructions
        return Question(el, "choice", text=text, choices=choices, links=links, marked_wrong=marked)

    # ---- answering -----------------------------------------------------

    def _answer_choice(self, q: Question) -> bool:
        self._set("answering", q.text.replace("\n", "  "))
        n = len(q.choices)

        # Choices known to be wrong for this question: marked on the page, or failed earlier in
        # this run (kept across retries and reloads, keyed by question + choices).
        key = cache_key(q.text, q.choices)
        if len(self._failed) > 500:
            self._failed.clear()
        failed = self._failed.setdefault(key, set())
        tried = set(q.marked_wrong) | {i for i, c in enumerate(q.choices) if normalize(c) in failed}
        if len(tried) >= n:  # everything "failed" without the page confirming: start over
            failed.clear()
            tried = set(q.marked_wrong)

        def give_up_on(index: int) -> None:
            tried.add(index)
            failed.add(normalize(q.choices[index]))

        cached = self.store.lookup(q.text, q.choices)
        if cached is not None and cached in tried:
            self.log.info("Cached answer is marked wrong on the page, forgetting it: %s", q.choices[cached])
            self.store.forget(q.text, q.choices)
            cached = None

        if cached is not None:
            result = self._try(q, cached)
            if result == NOT_CLICKED:
                return False
            if result == RIGHT:
                self._count("cache_hits")
                self._count("correct_answers")
                self._failed.pop(key, None)
                return True
            if result == WRONG:
                self.log.info("Cached answer was wrong, forgetting it: %s", q.choices[cached])
                self.store.forget(q.text, q.choices)
                self._count("wrong_answers")
            else:
                self.log.info("No response to cached answer; trying another choice")
            give_up_on(cached)
            if self._redrawn(q):
                return False
        else:
            self._count("cache_misses")

        while len(tried) < n and not self.stop.is_set():
            remaining = [i for i in range(n) if i not in tried]
            index = remaining[0] if len(remaining) == 1 else self._ask_ai(q, tried)
            if index is None or index in tried:
                why = "No usable AI answer" if index is None else "AI repeated a wrong choice"
                index = remaining[0]
                self.log.info("%s, trying choice %d", why, index + 1)

            result = self._try(q, index)
            if result == NOT_CLICKED:
                return False
            if result == RIGHT:
                self.store.remember(q.text, q.choices, index)
                self._count("correct_answers")
                self._failed.pop(key, None)
                return True
            if result == WRONG:
                self._count("wrong_answers")
            else:
                self.log.info("No response to %r; treating it as wrong", q.choices[index])
            give_up_on(index)
            if self._redrawn(q):
                return False  # VocabTrainer redraws after a wrong pick; re-read it (failed picks are remembered)
        return False

    def _answer_image(self, q: Question) -> bool:
        self._set("answering", "Image question - trying each picture")
        # Pictures that already failed: marked on practice pages; remembered here for VocabTrainer,
        # which redraws the question after each pick instead of marking the picture.
        key = f"image|{q.text}|{len(q.links)}"
        failed = self._failed.setdefault(key, set())
        if len(failed) >= len(q.links):
            failed.clear()
        first = True
        for index in range(len(q.links)):
            if index in q.marked_wrong or str(index) in failed:
                continue
            result = self._try(q, index, pause=None if first else 0.5)
            first = False
            if result == NOT_CLICKED:
                return False
            if result == RIGHT:
                self._count("correct_answers")
                self._failed.pop(key, None)
                return True
            failed.add(str(index))
            if self._redrawn(q):
                return False
        return False

    def _answer_spelling(self, q: Question) -> bool:
        word_el = q.element.find_elements(By.CSS_SELECTOR, SEL_SPELLING_WORD)
        word = (word_el[0].get_attribute("innerText") or "").strip() if word_el else ""
        if not word:
            give_up = q.element.find_elements(By.CSS_SELECTOR, SEL_SURRENDER)
            if give_up and give_up[0].is_displayed() and not self._exists(SEL_NEXT):
                self._wait_for_turn()
                self.log.info("Spelling word not shown; using the page's give-up button")
                give_up[0].click()
                self._answered()
                self._count("wrong_answers")
                return True
            self.log.info("Spelling question without a visible word")
            return False
        self._set("answering", f"Spelling: {word}")
        if self._exists(SEL_NEXT):
            return False
        box = q.element.find_element(By.CSS_SELECTOR, SEL_SPELLING_INPUT)
        box.clear()
        self._wait_for_turn()
        box.send_keys(word + Keys.RETURN)
        self._answered()
        if self._await_result(None, self._latest_feedback()) == RIGHT:
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

    def _try(self, q: Question, index: int, pause: float | None = None) -> str:
        """Click a choice and report RIGHT, WRONG, NO_RESULT (clicked, page didn't say), or
        NOT_CLICKED (stopping, question already answered, or the click failed)."""
        if pause is None:
            self._wait_for_turn()
        else:
            self._sleep(pause)
        if self.stop.is_set():
            return NOT_CLICKED
        if self._exists(SEL_NEXT):
            return NOT_CLICKED  # already answered; the next tick clicks Next

        link = q.links[index]
        feedback_before = self._latest_feedback()
        try:
            link.click()
        except WebDriverException as e:
            self.log.info("Could not click choice %d: %s", index + 1, (e.msg or str(e)).splitlines()[0])
            return NOT_CLICKED
        self._answered()
        label = q.choices[index] if q.choices else f"picture {index + 1}"
        result = self._await_result(link, feedback_before)
        self.log.info("Picked %r: %s", label, result)
        return result

    def _schedule_next(self, base: float) -> None:
        self._answer_at = base + random.uniform(self.config.min_wait, self.config.max_wait)

    def _wait_for_turn(self) -> None:
        self._sleep(max(0.0, self._answer_at - time.monotonic()))

    def _answered(self) -> None:
        """Record a submitted answer; a retry on the same question waits a fresh interval."""
        self._last_answer = time.monotonic()
        self._schedule_next(self._last_answer)

    @staticmethod
    def _redrawn(q: Question) -> bool:
        """True if the page replaced this question's elements (VocabTrainer redraws after each pick)."""
        try:
            q.element.is_enabled()
            return False
        except StaleElementReferenceException:
            return True

    def _latest_feedback(self) -> tuple[str, bool] | None:
        """VocabTrainer's newest verdict block as (element id, was_correct), or None."""
        found = self._d.find_elements(By.CSS_SELECTOR, SEL_FEEDBACK)
        if not found:
            return None
        el = found[-1]
        try:
            return el.id, "box-feedback-correct" in (el.get_attribute("class") or "")
        except StaleElementReferenceException:
            return None

    def _await_result(self, link: WebElement | None, feedback_before: tuple[str, bool] | None = None) -> str:
        """Wait for the site's verdict. Practice pages add class `incorrect`/`correct` to the
        clicked choice; VocabTrainer redraws the question with a feedback block. Both show Next
        once the question is done, but VocabTrainer can show it after a wrong answer too, so
        the explicit verdicts are checked first."""
        deadline = time.monotonic() + RESULT_TIMEOUT
        while time.monotonic() < deadline and not self.stop.is_set():
            if link is not None:
                try:
                    classes = (link.get_attribute("class") or "").split()
                except StaleElementReferenceException:
                    classes = []  # the page redrew; the checks below tell us how it went
                if "incorrect" in classes:
                    return WRONG
                if "correct" in classes:
                    return RIGHT
            feedback = self._latest_feedback()
            if feedback is not None and feedback != feedback_before:
                return RIGHT if feedback[1] else WRONG
            if self._exists(SEL_NEXT):
                return RIGHT
            self._sleep(0.2)
        return NO_RESULT

    # ---- interstitials -------------------------------------------------

    # ---- choosing an assignment ----------------------------------------

    def request_assignment(self, assignment_id: str) -> str | None:
        """Ask this session to open one of its listed assignments. Called from the UI/CLI thread;
        the session thread does the navigation. Returns an error message or None."""
        if self.status.state not in IDLE_STATES:
            return f"{self.status.account or self.name} is busy; stop it or wait until it finishes."
        match = next((a for a in self.status.assignments if a["id"] == assignment_id), None)
        if match is None:
            return "That assignment isn't in this account's list any more."
        if not match["supported"]:
            return f"{match['kind_label']} assignments aren't supported yet; only Practice."
        with self._request_lock:
            self._open_request = (match["url"], match["name"])
        return None

    def request_vocabtrainer(self) -> str | None:
        """Ask this session to open VocabTrainer. It keeps going until stopped."""
        if self.status.state not in IDLE_STATES:
            return f"{self.status.account or self.name} is busy; stop it or wait until it finishes."
        with self._request_lock:
            self._open_request = (VOCABTRAINER_URL, "VocabTrainer")
        return None

    def _open_requested(self) -> bool:
        with self._request_lock:
            request, self._open_request = self._open_request, None
        if request is None:
            return False
        url, name = request
        self.log.info("Opening assignment %s", name)
        self._set("opening", f"Opening {name}")
        self._finished_seen = False
        self._current = None
        self._opened_at = time.monotonic()
        self._d.get(url)
        self._sleep(2)
        return True

    def _refresh_assignments(self) -> None:
        """Re-read the unfinished assignments while idle: right after sign-in or finishing one,
        then once a minute. Needs the account to be signed in."""
        if not self.status.account or self.status.state not in IDLE_STATES + ("starting", "launching"):
            return
        now = time.monotonic()
        if not self._assignments_dirty and now - self._assignments_checked < ASSIGNMENTS_REFRESH:
            return
        self._assignments_checked, self._assignments_dirty = now, False
        try:
            self._d.set_script_timeout(15)
            raw = self._d.execute_async_script(assignment_list.FETCH_JS) or {}
        except WebDriverException as e:
            self.log.info("Couldn't read assignments: %s", (e.msg or str(e)).splitlines()[0])
            return
        items, source = assignment_list.parse(raw)
        if source == "none":
            return
        if source == "cached":
            self.log.info("Assignment list from the site's cached copy (%s)", raw.get("apiError") or "live list unavailable")
        self.status.assignments = [a.to_dict() for a in items]
        self.status.assignments_loaded = True

    def _show_idle_state(self) -> None:
        if self.status.state == "done":
            return  # keep "done" until the next assignment starts
        todo = [a for a in self.status.assignments if a["supported"]]
        if not self.status.account:
            self._set_if_changed("waiting", "Sign in to Vocabulary.com in this window")
        elif not self.status.assignments_loaded:
            self._set_if_changed("waiting", "Loading assignments")
        elif todo:
            self._set_if_changed("choosing", "Choose an assignment")
        else:
            self._set_if_changed("choosing", "No practice assignments to do. Start VocabTrainer instead.")

    def _set_if_changed(self, state: str, detail: str) -> None:
        if (self.status.state, self.status.detail) != (state, detail):
            self._set(state, detail)

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
            self._assignments_dirty = True
        self.status.account = name

    def _wait_out_lockout(self) -> bool:
        """VocabTrainer's "Woah, that's fast!" pause. It clears itself when its timer runs out."""
        if not self._exists(SEL_LOCKOUT):
            return False
        timer = self._d.find_elements(By.CSS_SELECTOR, SEL_LOCKOUT_TIMER)
        left = timer[0].text.strip() if timer else ""
        if self.status.state != "paused":
            self.log.info("VocabTrainer paused play for a break%s", f" ({left} left)" if left else "")
        self._set("paused", "VocabTrainer asked for a break" + (f", continues in {left}" if left else ""))
        self._current = None
        self._last_question_at = time.monotonic()  # resuming afterwards is the same session of play
        self._sleep(5)
        return True

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
