import json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from time import sleep, time
from openai import OpenAI
import re
import os
import sys
from PyQt6.QtWidgets import QMessageBox

class VocabAutomation:
    def __init__(self, config, status_callback=None, stats_callback=None, log_callback=None, skip_browser_setup=False):
        self.config = config
        self.running = True
        self.statistics = {
            "correct_answers": 0,
            "wrong_answers": 0,
            "achievements": 0,
            "cache_hits": 0  # New statistic for cache hits
        }
        self.status_callback = status_callback
        self.stats_callback = stats_callback
        self.log_callback = log_callback
        self.last_question_text = ""
        self.last_question_container = None
        self.last_input_field = None
        self.ready_to_start = False
        self.question_cache = {}
        self.driver = None
        self.wait = None
        self.chrome_log_file = None
        self.completion_callback = None
        
        self.setup_openai()
        self.load_statistics()
        self.load_question_cache()
        
        if not skip_browser_setup:
            self.setup_browser()

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def update_status(self, message):
        if self.status_callback:
            self.status_callback(message)
        self.log(message)

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

    def load_question_cache(self):
        try:
            with open('question_cache.json', 'r') as f:
                self.question_cache = json.load(f)
            self.update_status(f"Loaded {len(self.question_cache)} cached questions")
        except FileNotFoundError:
            self.question_cache = {}
            self.save_question_cache()

    def save_question_cache(self):
        with open('question_cache.json', 'w') as f:
            json.dump(self.question_cache, f, indent=4)

    def get_cache_key(self, question, choices):
        """Create a unique key for the question and its choices"""
        # Normalize the question text
        question = re.sub(r'\s+', ' ', question.strip().lower())
        # Normalize and sort choices for consistency
        choices = [re.sub(r'\s+', ' ', choice.strip().lower()) for choice in choices]
        choices.sort()  # Sort choices to ensure consistent key regardless of order
        # Combine question and choices into a single string
        full_text = question + ''.join(choices)
        return full_text

    def get_cached_answer(self, question, choices):
        """Try to get an answer from the cache"""
        cache_key = self.get_cache_key(question, choices)
        cached_data = self.question_cache.get(cache_key)
        
        if not cached_data:
            return None

        # Verify the choices match (case-insensitive)
        cached_choices = [choice.lower() for choice in cached_data['choices']]
        current_choices = [choice.lower() for choice in choices]
        
        if sorted(cached_choices) == sorted(current_choices):
            self.update_status("Using cached answer!")
            self.statistics["cache_hits"] += 1
            self.save_statistics()
            return cached_data['correct_index']
        
        return None

    def cache_correct_answer(self, question, choices, correct_index):
        """Cache a correct answer for future use"""
        cache_key = self.get_cache_key(question, choices)
        
        # Only update cache if this is a new answer or if the existing answer is different
        existing_data = self.question_cache.get(cache_key)
        if not existing_data or existing_data['correct_index'] != correct_index:
            self.question_cache[cache_key] = {
                'question': question,
                'choices': choices,
                'correct_index': correct_index,
                'last_used': time(),
                'times_used': 1
            }
            self.save_question_cache()
            self.update_status("Added new answer to cache")
        elif existing_data:
            # Update usage statistics for existing cache entry
            existing_data['times_used'] += 1
            existing_data['last_used'] = time()
            self.save_question_cache()

    def handle_answer_result(self, question, choices, choice_index, was_correct):
        """Handle the result of an answer attempt"""
        if was_correct:
            self.cache_correct_answer(question, choices, choice_index)
            self.statistics["correct_answers"] += 1
            self.save_statistics()
            self.wait_and_click_next()
        else:
            # If answer was wrong, remove it from cache if it exists
            cache_key = self.get_cache_key(question, choices)
            if cache_key in self.question_cache:
                del self.question_cache[cache_key]
                self.save_question_cache()
                self.update_status("Removed incorrect answer from cache")
            
            self.statistics["wrong_answers"] += 1
            self.save_statistics()

    def setup_browser(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            
        options = uc.ChromeOptions()
        
        # Handle chrome driver output suppression
        if self.config["chrome_options"].get("suppress_errors", True):
            if not os.path.exists("chrome_logs"):
                os.makedirs("chrome_logs")
            # Close previous log file if it exists
            if self.chrome_log_file:
                try:
                    sys.stderr = sys.__stderr__
                    self.chrome_log_file.close()
                except Exception:
                    pass
            # Open new log file
            self.chrome_log_file = open("chrome_logs/chrome_errors.log", "w")
            sys.stderr = self.chrome_log_file

        # macOS specific options
        options.add_argument('--allow-running-insecure-content')
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--disable-web-security')
        options.add_argument('--disable-features=IsolateOrigins,site-per-process')
        
        # Add standard options
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-software-rasterizer')
        
        # Add user-configured options
        for option, value in self.config["chrome_options"].items():
            if isinstance(value, bool) and value and option != "suppress_errors":
                options.add_argument(f"--{option.replace('_', '-')}")
            elif isinstance(value, str):
                options.add_argument(f"--{option.replace('_', '-')}={value}")
        
        self.update_status("Starting browser...")
        try:
            # Try with default configuration first
            try:
                self.driver = uc.Chrome(options=options)
            except Exception as e1:
                self.update_status(f"First browser launch attempt failed: {str(e1)}")
                # If first attempt fails, try with additional options
                options.add_argument('--no-first-run')
                options.add_argument('--no-default-browser-check')
                options.add_argument('--disable-blink-features=AutomationControlled')
                
                try:
                    self.driver = uc.Chrome(options=options, use_subprocess=True)
                except Exception as e2:
                    self.update_status(f"Second browser launch attempt failed: {str(e2)}")
                    # If both attempts fail, try one last time with minimal options
                    options = uc.ChromeOptions()
                    options.add_argument('--no-sandbox')
                    options.add_argument('--disable-dev-shm-usage')
                    self.driver = uc.Chrome(options=options)
            
            self.wait = WebDriverWait(self.driver, 10)
            self.update_status("Browser started successfully")
        except Exception as e:
            self.update_status(f"Failed to start browser: {str(e)}")
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            raise

    def check_if_wrong(self, current_question, timeout=3):
        """Check if the answer was wrong by waiting for a new question"""
        start_time = time()
        while time() - start_time < timeout:
            try:
                # Check for wrong answer indicator
                wrong_indicators = self.driver.find_elements(
                    By.CSS_SELECTOR, ".wrong"
                )
                if wrong_indicators:
                    self.update_status("Previous answer was wrong")
                    return True
                
                # Check if next button is active (meaning correct)
                next_buttons = self.driver.find_elements(
                    By.CSS_SELECTOR, "button.next.active[aria-label='Next question']"
                )
                if next_buttons:
                    return False
                    
                sleep(0.2)
            except Exception:
                pass
        
        self.update_status("No confirmation of correct answer, assuming wrong")
        return True

    def get_openai_response(self, question, choices, previous_wrong_answers=None):
        self.update_status("Getting AI response...")
        prompt = f"Question: {question}\nChoices:\n"
        for i, choice in enumerate(choices, start=1):
            prompt += f"{i}. {choice}\n"
        
        if previous_wrong_answers:
            prompt += "\nPrevious incorrect answers were: "
            prompt += ", ".join([f"choice {i+1}" for i in previous_wrong_answers])
            prompt += ". Please choose a different answer."
        
        prompt += "\nWhich one is correct? Just respond with the number (1-4)."

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
            
            if input_field == self.last_input_field:
                self.update_status("Waiting for new input field...")
                self.wait.until(EC.staleness_of(self.last_input_field))
                input_field = current_container.find_element(
                    By.CSS_SELECTOR, "input.wordspelling"
                )
            
            self.last_input_field = input_field
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
                self.last_question_text = ""
                self.last_question_container = None
                self.last_input_field = None
                
                # Click the next button to continue to next round
                try:
                    next_button = self.wait.until(
                        EC.element_to_be_clickable(
                            (By.CSS_SELECTOR, "button.next.active[aria-label='Next question']")
                        )
                    )
                    next_button.click()
                    self.update_status("Moving to next round...")
                    sleep(1)
                except Exception as e:
                    self.update_status(f"Error clicking next after round complete: {str(e)}")
                
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
                self.update_status("Assignment complete!")
                
                # Show completion message
                QMessageBox.information(None, "Assignment Complete", 
                    "The current assignment has been completed!\n\n"
                    "To start a new assignment:\n"
                    "1. Select your next assignment\n"
                    "2. Click 'Start Automation'\n"
                    "3. Click 'Ready to Start' when ready"
                )
                
                # Save final statistics
                self.save_statistics()
                self.save_question_cache()
                
                # Stop the automation
                self.running = False
                
                # Call completion callback if set
                if self.completion_callback:
                    self.completion_callback()
                    
                return True
        except Exception:
            pass
        return False

    def is_image_question(self, current_container):
        try:
            class_attr = current_container.get_attribute("class")
            data_template = current_container.get_attribute("data-template")
            return any(class_name in class_attr for class_name in ["typeI", "multiple-image"]) or data_template == "multiple-image"
        except Exception as e:
            self.update_status(f"Error checking image question: {str(e)}")
            return False

    def handle_image_question(self, current_container, links):
        self.update_status("Image question detected - trying all options...")
        max_attempts = 4
        attempts = 0
        
        # Get the word being asked about
        try:
            word_div = current_container.find_element(By.CSS_SELECTOR, ".word")
            word = word_div.text.strip()
            self.update_status(f"Finding image for word: {word}")
        except Exception:
            self.update_status("Could not find word for image question")
        
        while attempts < max_attempts:
            if not self.running:
                return False
                
            for i, link in enumerate(links, 1):
                try:
                    self.update_status(f"Attempt {attempts + 1}/{max_attempts} - Trying image {i} of {len(links)}...")
                    link.click()
                    sleep(0.5)  # Small delay between clicks
                    
                    # Check for wrong indicator
                    wrong_indicators = self.driver.find_elements(By.CSS_SELECTOR, ".wrong")
                    if wrong_indicators:
                        continue
                    
                    # Check if next button appears (meaning we got it right)
                    next_buttons = self.driver.find_elements(
                        By.CSS_SELECTOR, "button.next.active[aria-label='Next question']"
                    )
                    if next_buttons:
                        self.update_status("Found correct image!")
                        self.statistics["correct_answers"] += 1
                        self.save_statistics()
                        self.wait_and_click_next()
                        return True
                except Exception as e:
                    self.update_status(f"Error clicking image {i}: {str(e)}")
                    continue
            
            attempts += 1
            if attempts < max_attempts:
                self.update_status(f"No correct image found, trying again... (Attempt {attempts + 1}/{max_attempts})")
            sleep(0.5)
        
        self.update_status("Could not find correct image after all attempts")
        self.statistics["wrong_answers"] += 1
        self.save_statistics()
        return False

    def get_question_and_choices(self):
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".question")))
            question_containers = self.driver.find_elements(By.CSS_SELECTOR, ".question")
            
            if not question_containers:
                self.update_status("No questions found")
                return None, None, None

            current_container = question_containers[-1]
            
            if current_container == self.last_question_container:
                self.update_status("Waiting for new question...")
                self.wait.until(EC.staleness_of(self.last_question_container))
                question_containers = self.driver.find_elements(By.CSS_SELECTOR, ".question")
                current_container = question_containers[-1]
            
            self.last_question_container = current_container

            # Check for image question first
            if self.is_image_question(current_container):
                choices_div = current_container.find_element(By.CSS_SELECTOR, ".choices")
                links = choices_div.find_elements(By.TAG_NAME, "a")
                return "image_question", [], links
            
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

            if question == self.last_question_text:
                self.update_status("Waiting for new question text...")
                return None, None, None

            self.last_question_text = question
            self.update_status(f"Processing question: {question}")
            return question, choices, links

        except Exception as e:
            self.update_status(f"Error getting question: {str(e)}")
            return None, None, None

    def set_ready(self):
        self.ready_to_start = True

    def set_completion_callback(self, callback):
        self.completion_callback = callback

    def run(self):
        try:
            self.setup_browser()
            self.driver.get("https://www.vocabulary.com/account/activities/")
            self.update_status("Please sign in, select your assignment, then click 'Ready to Start'")
            
            # Wait for user to be ready
            while not self.ready_to_start and self.running:
                sleep(1)
                continue

            if not self.running:
                return

            self.update_status(f"Starting automation (Cache size: {len(self.question_cache)} entries)")
            
            while self.running:
                if not self.running:
                    break

                if self.check_achievement() or self.check_round_complete():
                    continue

                if self.check_finished():
                    break

                question, choices, links = self.get_question_and_choices()
                
                if not all([links]):  # Only check links since choices might be empty for image questions
                    sleep(1)
                    continue

                # Handle image question
                if question == "image_question":
                    self.handle_image_question(self.last_question_container, links)
                    continue

                # Try cached answer first
                cached_index = self.get_cached_answer(question, choices)
                if cached_index is not None and 0 <= cached_index < len(links):
                    self.update_status(f"Using cached answer: {choices[cached_index]}")
                    links[cached_index].click()
                    
                    if not self.check_if_wrong(question):
                        self.handle_answer_result(question, choices, cached_index, True)
                        continue
                    else:
                        self.update_status("Cached answer was wrong, removing from cache and trying AI...")
                        # Remove incorrect cached answer
                        cache_key = self.get_cache_key(question, choices)
                        if cache_key in self.question_cache:
                            del self.question_cache[cache_key]
                            self.save_question_cache()

                # If no cache hit or cached answer was wrong, try AI
                wrong_answers = []
                max_retries = 4
                
                for attempt in range(max_retries):
                    answer = self.get_openai_response(question, choices, wrong_answers)
                    
                    if answer and (match := re.search(r"[1-4]", answer)):
                        choice_index = int(match.group()) - 1
                        if 0 <= choice_index < len(links):
                            if choice_index in wrong_answers:
                                self.update_status("AI suggested a previously wrong answer, trying again...")
                                continue
                                
                            links[choice_index].click()
                            self.update_status(f"Selected answer: {choices[choice_index]}")
                            
                            # Check if the answer was wrong
                            if self.check_if_wrong(question):
                                wrong_answers.append(choice_index)
                                self.handle_answer_result(question, choices, choice_index, False)
                                
                                if attempt < max_retries - 1:
                                    self.update_status(f"Answer was wrong, trying again... (Attempt {attempt + 2}/{max_retries})")
                                    continue
                            else:
                                self.handle_answer_result(question, choices, choice_index, True)
                                break
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
        try:
            if hasattr(self, 'driver'):
                self.driver.quit()
                delattr(self, 'driver')
            
            # Close chrome log file if it exists
            if hasattr(self, 'chrome_log_file'):
                sys.stderr = sys.__stderr__  # Restore original stderr
                self.chrome_log_file.close()
                delattr(self, 'chrome_log_file')
                
            # Save any pending changes
            self.save_statistics()
            self.save_question_cache()
        except Exception as e:
            self.update_status(f"Error during cleanup: {str(e)}")

    def __del__(self):
        self.stop() 