import json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from time import sleep
from openai import OpenAI
import re

class VocabAutomation:
    def __init__(self, config):
        self.config = config
        self.running = True
        self.statistics = {
            "correct_answers": 0,
            "wrong_answers": 0,
            "achievements": 0
        }
        self.status_callback = None
        self.stats_callback = None
        self.setup_openai()
        self.load_statistics()

    def setup_openai(self):
        self.client = OpenAI(api_key=self.config["openai_api_key"])

    def load_statistics(self):
        try:
            with open('statistics.json', 'r') as f:
                self.statistics.update(json.load(f))
                if self.stats_callback:
                    self.stats_callback(self.statistics)
        except FileNotFoundError:
            self.save_statistics()

    def save_statistics(self):
        with open('statistics.json', 'w') as f:
            json.dump(self.statistics, f, indent=4)
        if self.stats_callback:
            self.stats_callback(self.statistics)

    def update_status(self, message):
        if self.status_callback:
            self.status_callback(message)

    def setup_browser(self):
        options = uc.ChromeOptions()
        for option, value in self.config["chrome_options"].items():
            if isinstance(value, bool) and value:
                options.add_argument(f"--{option.replace('_', '-')}")
            elif isinstance(value, str):
                options.add_argument(f"--{option.replace('_', '-')}={value}")
        
        self.update_status("Starting browser...")
        self.driver = uc.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 10)
        self.update_status("Browser started successfully")

    def get_openai_response(self, question, choices):
        self.update_status("Getting AI response...")
        prompt = f"Question: {question}\nChoices:\n"
        for i, choice in enumerate(choices, start=1):
            prompt += f"{i}. {choice}\n"
        prompt += "Which one is correct? Just respond with the number (1-4)."

        try:
            completion = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            answer = completion.choices[0].message.content.strip()
            self.update_status(f"AI suggested answer: {answer}")
            return answer
        except Exception as e:
            self.update_status(f"Error getting AI response: {str(e)}")
            return None

    def solve_audio_question(self, current_container):
        try:
            self.update_status("Solving audio question...")
            sentence_div = current_container.find_element(
                By.CSS_SELECTOR, "div.sentence.complete"
            )
            
            word = self.driver.execute_script(
                "return arguments[0].querySelector('strong').innerText;",
                sentence_div
            )
            
            if not word:
                self.update_status("Could not find word in audio question")
                return False

            input_field = current_container.find_element(
                By.CSS_SELECTOR, "input.wordspelling"
            )
            
            input_field.clear()
            input_field.send_keys(word + Keys.RETURN)
            self.update_status(f"Entered word: {word}")
            
            self.wait_and_click_next()
            return True

        except Exception as e:
            self.update_status(f"Error in audio question: {str(e)}")
            return False

    def wait_and_click_next(self):
        try:
            next_button = self.wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button.next.active[aria-label='Next question']")
                )
            )
            next_button.click()
            sleep(1)
            return True
        except Exception as e:
            self.update_status(f"Error clicking next: {str(e)}")
            return False

    def check_achievement(self):
        try:
            achievement_elements = self.driver.find_elements(
                By.CSS_SELECTOR, ".hero.with-header-padding"
            )
            for achievement in achievement_elements:
                is_processed = self.driver.execute_script(
                    "return arguments[0].getAttribute('data-processed');",
                    achievement
                )
                if not is_processed:
                    self.update_status("Achievement unlocked!")
                    self.statistics["achievements"] += 1
                    self.save_statistics()
                    
                    self.wait_and_click_next()
                    self.driver.execute_script(
                        "arguments[0].setAttribute('data-processed', 'true');",
                        achievement
                    )
                    return True
        except Exception:
            pass
        return False

    def check_round_complete(self):
        try:
            complete_elements = self.driver.find_elements(
                By.CSS_SELECTOR, "h1 svg.progress-icon"
            )
            if complete_elements:
                self.update_status("Round complete!")
                return True
        except Exception:
            pass
        return False

    def check_finished(self):
        try:
            finished_element = self.driver.find_element(
                By.CSS_SELECTOR, ".practiceComplete.activity-summary"
            )
            if finished_element:
                self.update_status("Practice session complete!")
                return True
        except Exception:
            pass
        return False

    def get_question_and_choices(self):
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".question")))
            question_containers = self.driver.find_elements(By.CSS_SELECTOR, ".question")
            
            if not question_containers:
                self.update_status("No questions found")
                return None, None, None

            current_container = question_containers[-1]
            
            # Check for audio question
            audio_button = current_container.find_elements(
                By.CSS_SELECTOR, "button.playword.ss-highvolume"
            )
            if audio_button:
                if self.solve_audio_question(current_container):
                    return None, None, None

            # Get sentence context if available
            sentence_context = ""
            try:
                sentence_div = current_container.find_element(
                    By.CSS_SELECTOR, ".sentence"
                )
                sentence_context = sentence_div.text.strip()
            except Exception:
                pass

            # Get choices
            choices_div = current_container.find_element(By.CSS_SELECTOR, ".choices")
            links = choices_div.find_elements(By.TAG_NAME, "a")
            choices = [link.text.strip() for link in links]

            if not any(choices):
                self.update_status("Waiting for choices to load...")
                return None, None, None

            # Get question
            instructions_div = current_container.find_element(
                By.CSS_SELECTOR, ".instructions"
            )
            question = instructions_div.text.replace("\n", " ").strip()

            if sentence_context:
                question = f"{question}\nContext: {sentence_context}"

            self.update_status(f"Processing question: {question}")
            return question, choices, links

        except Exception as e:
            self.update_status(f"Error getting question: {str(e)}")
            return None, None, None

    def run(self):
        try:
            self.setup_browser()
            self.driver.get("https://www.vocabulary.com/account/activities/")
            self.update_status("Please sign in and select your assignment...")
            
            while self.running:
                if not self.running:
                    break

                if self.check_achievement() or self.check_round_complete():
                    continue

                if self.check_finished():
                    self.update_status("Session finished! Press Start to begin a new session.")
                    break

                question, choices, links = self.get_question_and_choices()
                
                if not all([question, choices, links]):
                    sleep(1)
                    continue

                answer = self.get_openai_response(question, choices)
                
                if answer and (match := re.search(r"[1-4]", answer)):
                    choice_index = int(match.group()) - 1
                    if 0 <= choice_index < len(links):
                        links[choice_index].click()
                        self.update_status(f"Selected answer: {choices[choice_index]}")
                        self.statistics["correct_answers"] += 1
                        self.save_statistics()
                        self.wait_and_click_next()
                    else:
                        self.update_status("Invalid answer index")
                        self.statistics["wrong_answers"] += 1
                        self.save_statistics()
                else:
                    self.update_status("Could not determine answer")
                    self.statistics["wrong_answers"] += 1
                    self.save_statistics()

                sleep(2)

        except Exception as e:
            self.update_status(f"Error in automation: {str(e)}")
            raise
        finally:
            if hasattr(self, 'driver'):
                self.driver.quit()

    def stop(self):
        self.running = False
        if hasattr(self, 'driver'):
            self.driver.quit() 