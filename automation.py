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
import atexit
import multiprocessing
from PyQt6.QtWidgets import QMessageBox
import psutil
import threading
import traceback
import logging
import platform
import signal
import gc
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.table import Table
from rich import box
from datetime import datetime

# Initialize rich console
console = Console()

class TerminalUI:
    def __init__(self):
        self.console = Console()
        self.layout = Layout()
        self.last_status = ""
        self.last_question = ""
        self.statistics = {}
        self.start_time = datetime.now()
        
    def create_stats_table(self, stats):
        """Create a beautiful statistics table"""
        table = Table(box=box.ROUNDED, expand=True)
        table.add_column("Statistic", style="cyan")
        table.add_column("Value", justify="right", style="green")
        
        for key, value in stats.items():
            # Convert snake_case to Title Case
            display_key = " ".join(word.capitalize() for word in key.split("_"))
            table.add_row(display_key, str(value))
            
        # Add runtime
        runtime = datetime.now() - self.start_time
        hours = runtime.seconds // 3600
        minutes = (runtime.seconds % 3600) // 60
        seconds = runtime.seconds % 60
        table.add_row("Runtime", f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        
        return table

    def create_status_panel(self):
        """Create a panel for status messages"""
        return Panel(
            self.last_status,
            title="Status",
            border_style="blue",
            box=box.ROUNDED
        )

    def create_question_panel(self):
        """Create a panel for the current question"""
        return Panel(
            self.last_question or "Waiting for question...",
            title="Current Question",
            border_style="yellow",
            box=box.ROUNDED
        )

    def update_display(self, status=None, question=None, stats=None):
        """Update the terminal display"""
        if status:
            self.last_status = status
        if question:
            self.last_question = question
        if stats:
            self.statistics = stats

        # Create layout
        self.layout.split(
            Layout(name="upper"),
            Layout(name="lower")
        )
        
        self.layout["upper"].split_row(
            Layout(self.create_stats_table(self.statistics), name="stats", ratio=1),
            Layout(self.create_status_panel(), name="status", ratio=2)
        )
        
        self.layout["lower"].update(self.create_question_panel())
        
        # Clear screen and render
        console.clear()
        console.print(self.layout)

# Configure logging based on config
def setup_logging(config):
    log_level = config.get('log_level', 'INFO').upper()
    enable_logging = config.get('enable_logging', False)
    
    if enable_logging:
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('automation.log')
            ]
        )
    else:
        # Disable all logging if not enabled
        logging.getLogger().setLevel(logging.CRITICAL)

# Global variables
_global_cleanup_initiated = False

def signal_handler(signum, frame):
    """Handle system signals gracefully"""
    logging.info(f"Received signal {signum}")
    cleanup_chrome_processes()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class TimeoutError(Exception):
    pass

class ThreadWithTimeout(threading.Thread):
    def __init__(self, target, args=(), kwargs=None):
        super().__init__()
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.result = None
        self.error = None
        self.daemon = True  # Make thread daemon so it doesn't prevent program exit

    def run(self):
        try:
            self.result = self.target(*self.args, **self.kwargs)
        except Exception as e:
            self.error = e
            logging.error(f"Error in thread: {str(e)}")
            logging.error(f"Stack trace:\n{traceback.format_exc()}")

def run_with_timeout(func, args=(), kwargs=None, timeout=30):
    """Run a function with a timeout in a thread-safe way"""
    kwargs = kwargs or {}
    thread = ThreadWithTimeout(target=func, args=args, kwargs=kwargs)
    thread.start()
    thread.join(timeout)
    
    if thread.is_alive():
        logging.error(f"Operation timed out after {timeout} seconds")
        return None
    if thread.error:
        raise thread.error
    return thread.result

def get_platform_options():
    """Get platform-specific Chrome options"""
    options = {
        'universal': [
            '--disable-extensions',
            '--disable-notifications',
            '--enable-automation',
            '--disable-blink-features=AutomationControlled',
            '--no-first-run',
            '--no-default-browser-check',
            '--window-size=1920,1080'
        ],
        'Darwin': [  # macOS specific
            '--disable-gpu',
            '--disable-dev-shm-usage',
            '--disable-features=TranslateUI',
            '--allow-running-insecure-content',
            '--ignore-certificate-errors',
            '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process',
            '--disable-site-isolation-trials'
        ],
        'Windows': [  # Windows specific
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-dev-shm-usage'
        ],
        'Linux': [  # Linux specific
            '--disable-gpu',
            '--no-sandbox',
            '--disable-dev-shm-usage'
        ]
    }
    
    system = platform.system()
    chrome_options = options['universal'].copy()
    
    if system in options:
        chrome_options.extend(options[system])
        
    return chrome_options

def cleanup_chrome_processes():
    """Clean up any remaining Chrome processes"""
    global _global_cleanup_initiated
    
    if _global_cleanup_initiated:
        return
        
    try:
        # Mark cleanup as initiated
        _global_cleanup_initiated = True
        
        # Force garbage collection first
        gc.collect()
        
        # Clear any remaining multiprocessing resources
        if hasattr(multiprocessing, 'resource_tracker'):
            try:
                multiprocessing.resource_tracker._resource_tracker.clear()
            except Exception as e:
                logging.error(f"Error clearing resource tracker: {str(e)}")
        
        system = platform.system()
        if system == 'Windows':
            os.system('taskkill /F /IM chrome.exe /T >nul 2>&1')
            os.system('taskkill /F /IM chromedriver.exe /T >nul 2>&1')
        elif system == 'Darwin':  # macOS
            os.system('pkill -9 -f "Google Chrome" >/dev/null 2>&1')
            os.system('pkill -9 -f "chromedriver" >/dev/null 2>&1')
        else:  # Linux and others
            os.system('pkill -9 -f chrome >/dev/null 2>&1')
            os.system('pkill -9 -f chromedriver >/dev/null 2>&1')
            
        # Small delay to ensure processes are cleaned up
        sleep(0.5)
        
    except Exception as e:
        logging.error(f"Error in cleanup_chrome_processes: {str(e)}")
    finally:
        # Reset cleanup flag
        _global_cleanup_initiated = False

# Register the cleanup function to run at exit
atexit.register(cleanup_chrome_processes)

class VocabAutomation:
    def __init__(self, config, status_callback=None, stats_callback=None, log_callback=None, skip_browser_setup=False):
        # Initialize terminal UI
        self.ui = TerminalUI()
        
        # Initialize threading controls
        self._thread_lock = threading.RLock()
        self._driver_lock = threading.RLock()
        self._cleanup_lock = threading.Lock()
        self._cleanup_called = False
        self._completion_called = False
        
        # Initialize state
        self.config = config
        self.running = True
        self.ready_to_start = False
        self.driver = None
        self.wait = None
        self.client = None
        self.last_question_text = ""
        self.last_question_container = None
        self.last_input_field = None
        
        # Callbacks
        self.status_callback = status_callback
        self.stats_callback = stats_callback
        self.log_callback = log_callback
        self.completion_callback = None
        
        # Setup logging
        setup_logging(config)
        
        # Cache and statistics
        self.statistics = {
            "correct_answers": 0,
            "wrong_answers": 0,
            "achievements": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_invalidations": 0
        }
        self.question_cache = {}
        self.cache_expiry_days = 30
        self.max_cache_size = 1000
        
        try:
            self.setup_openai()
            self.load_statistics()
            self.load_question_cache()
            self.prune_cache()
            
            if not skip_browser_setup:
                self.setup_browser()
        except Exception as e:
            self.log(f"Error in initialization: {str(e)}", 'error')
            self.cleanup()
            raise

    def log(self, message, level='info'):
        """Log a message to both the callback and the logging system"""
        if self.log_callback:
            self.log_callback(message)
        else:
            # Only use logging if no callback is provided
            log_func = getattr(logging, level)
            log_func(message)

    def update_status(self, message, level='info'):
        """Update status in terminal UI and log if enabled"""
        if self.config.get('enable_logging', False):
            log_func = getattr(logging, level)
            log_func(message)
        
        self.ui.update_display(status=message, stats=self.statistics)

    def update_question(self, question):
        """Update current question display"""
        self.ui.update_display(question=question, stats=self.statistics)

    def setup_openai(self):
        """Set up OpenAI client with retry mechanism"""
        try:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.client = OpenAI(api_key=self.config["openai_api_key"])
                    # Test the client
                    self.client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": "test"}],
                        max_tokens=5
                    )
                    self.update_status("OpenAI API connection successful")
                    return
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.update_status(f"Error setting up OpenAI (attempt {attempt + 1}): {str(e)}")
                        sleep(2)
                        continue
                    raise
        except Exception as e:
            self.update_status(f"Failed to set up OpenAI API: {str(e)}")
            raise

    def load_statistics(self):
        try:
            with open('statistics.json', 'r') as f:
                self.statistics.update(json.load(f))
                if self.stats_callback:
                    self.stats_callback(self.statistics)
        except FileNotFoundError:
            self.save_statistics()

    def save_statistics(self):
        """Thread-safe statistics saving"""
        with self._thread_lock:
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
        """Thread-safe cache saving"""
        with self._thread_lock:
            with open('question_cache.json', 'w') as f:
                json.dump(self.question_cache, f, indent=4)

    def get_cache_key(self, question, choices):
        """Create a unique key for the question and its choices"""
        try:
            # Remove context and any extra whitespace/newlines
            question = re.sub(r'Context:.*$', '', question, flags=re.MULTILINE).strip()
            question = re.sub(r'\s+', ' ', question).lower()
            
            # Remove punctuation and normalize whitespace
            question = re.sub(r'[^\w\s]', '', question)
            question = ' '.join(question.split())
            
            # Normalize and sort choices (remove punctuation and extra spaces)
            choices = [re.sub(r'[^\w\s]', '', choice.lower().strip()) for choice in choices]
            choices = [' '.join(choice.split()) for choice in choices]
            choices.sort()
            
            cache_key = f"{question}|{'|'.join(choices)}"
            self.log(f"Cache key generated: {cache_key}", 'debug')
            return cache_key
        except Exception as e:
            self.log(f"Error generating cache key: {str(e)}", 'error')
            return None

    def validate_cache_entry(self, entry, choices):
        """Validate a cache entry against current choices"""
        try:
            if not entry or not isinstance(entry, dict):
                self.log("Invalid cache entry format", 'debug')
                return False
            
            if 'correct_index' not in entry or not isinstance(entry['correct_index'], int):
                self.log("Missing or invalid correct_index in cache entry", 'debug')
                return False
            
            if 'choices' not in entry or not entry['choices']:
                self.log("Missing choices in cache entry", 'debug')
                return False
            
            # Normalize both sets of choices (remove punctuation and extra spaces)
            cached_choices = [re.sub(r'[^\w\s]', '', choice.lower().strip()) for choice in entry['choices']]
            cached_choices = [' '.join(choice.split()) for choice in cached_choices]
            
            current_choices = [re.sub(r'[^\w\s]', '', choice.lower().strip()) for choice in choices]
            current_choices = [' '.join(choice.split()) for choice in current_choices]
            
            cached_choices.sort()
            current_choices.sort()
            
            # Debug output
            self.log(f"Cached choices: {cached_choices}", 'debug')
            self.log(f"Current choices: {current_choices}", 'debug')
            
            return cached_choices == current_choices
            
        except Exception as e:
            self.log(f"Error validating cache entry: {str(e)}", 'error')
            return False

    def prune_cache(self):
        """Remove old or invalid entries from cache"""
        current_time = time()
        expiry_time = current_time - (self.cache_expiry_days * 24 * 3600)
        
        # Remove expired entries
        expired_keys = [
            key for key, entry in self.question_cache.items()
            if entry['last_used'] < expiry_time
        ]
        
        for key in expired_keys:
            del self.question_cache[key]
            self.statistics['cache_invalidations'] += 1
            
        # If still over size limit, remove least recently used entries
        if len(self.question_cache) > self.max_cache_size:
            sorted_entries = sorted(
                self.question_cache.items(),
                key=lambda x: (x[1]['last_used'], -x[1]['times_used'])
            )
            
            # Remove oldest entries until we're under the limit
            for key, _ in sorted_entries[:len(self.question_cache) - self.max_cache_size]:
                del self.question_cache[key]
                self.statistics['cache_invalidations'] += 1
        
        self.save_question_cache()
        self.save_statistics()

    def get_cached_answer(self, question, choices):
        """Thread-safe cache access"""
        try:
            if not question or not choices:
                return None
            
            cache_key = self.get_cache_key(question, choices)
            if not cache_key:
                return None
            
            self.log(f"Looking up cache key: {cache_key}", 'debug')
            
            with self._thread_lock:
                cached_data = self.question_cache.get(cache_key)
                
                if cached_data and self.validate_cache_entry(cached_data, choices):
                    self.update_status(f"Found cached answer: Choice #{cached_data['correct_index'] + 1}")
                    with self._thread_lock:
                        self.statistics["cache_hits"] += 1
                        self.save_statistics()
                    
                    # Update usage statistics
                    cached_data['last_used'] = time()
                    cached_data['times_used'] += 1
                    self.save_question_cache()
                    
                    return cached_data['correct_index']
            
            if cached_data:
                self.log("Cache entry found but validation failed", 'debug')
            else:
                self.log("No cache entry found", 'debug')
            
            with self._thread_lock:
                self.statistics["cache_misses"] += 1
                self.save_statistics()
            return None
            
        except Exception as e:
            self.log(f"Error accessing cache: {str(e)}", 'error')
            return None

    def cache_correct_answer(self, question, choices, correct_index):
        """Cache a correct answer for future use"""
        try:
            if not question or not choices or correct_index is None:
                return
            
            cache_key = self.get_cache_key(question, choices)
            if not cache_key:
                return
            
            current_time = time()
            
            # Store normalized versions of the choices
            normalized_choices = [re.sub(r'[^\w\s]', '', choice.lower().strip()) for choice in choices]
            normalized_choices = [' '.join(choice.split()) for choice in normalized_choices]
            
            self.question_cache[cache_key] = {
                'correct_index': correct_index,
                'choices': normalized_choices,
                'last_used': current_time,
                'times_used': 1,
                'first_seen': current_time
            }
            
            self.save_question_cache()
            self.update_status(f"Added answer to cache: Choice #{correct_index + 1}")
            
        except Exception as e:
            self.log(f"Error caching answer: {str(e)}", 'error')

    def handle_answer_result(self, question, choices, choice_index, was_correct):
        """Handle the result of an answer attempt"""
        try:
            if was_correct:
                self.cache_correct_answer(question, choices, choice_index)
                self.statistics["correct_answers"] += 1
                self.save_statistics()
                self.wait_and_click_next()
            else:
                # If answer was wrong, remove it from cache if it exists
                cache_key = self.get_cache_key(question, choices)
                if cache_key and cache_key in self.question_cache:
                    del self.question_cache[cache_key]
                    self.save_question_cache()
                    self.update_status("Removed incorrect answer from cache")
                
                self.statistics["wrong_answers"] += 1
                self.save_statistics()
        except Exception as e:
            self.log(f"Error handling answer result: {str(e)}", 'error')

    def setup_browser(self):
        """Set up the Chrome browser with basic options"""
        if self.driver is not None:
            return  # Don't setup browser if we already have one
        
        try:
            self.update_status("Setting up browser...")
            
            # Basic Chrome options
            options = uc.ChromeOptions()
            
            # Add platform-specific options
            for option in get_platform_options():
                options.add_argument(option)
            
            # Add user config options
            for option, value in self.config["chrome_options"].items():
                if isinstance(value, bool) and value:
                    options.add_argument(f"--{option.replace('_', '-')}")
                elif isinstance(value, str):
                    options.add_argument(f"--{option.replace('_', '-')}={value}")
            
            # Create driver with additional error handling
            self.driver = None  # Ensure driver is None before creating new one
            
            try:
                self.driver = uc.Chrome(options=options)
                if not self.driver:
                    raise Exception("Driver creation failed")
                
                # Test driver with simple command and verify it's responsive
                try:
                    self.driver.get("about:blank")
                    _ = self.driver.current_url  # Verify browser responds
                except Exception as e:
                    raise Exception(f"Browser not responsive after creation: {str(e)}")
                
                # Create WebDriverWait with timeout
                self.wait = WebDriverWait(self.driver, 10)
                
                self.update_status("Browser setup successful")
                
            except Exception as e:
                self.update_status(f"Error creating Chrome driver: {str(e)}")
                if self.driver:
                    try:
                        self.driver.quit()
                    except:
                        pass
                    self.driver = None
                raise
            
        except Exception as e:
            self.update_status(f"Error setting up browser: {str(e)}")
            self.cleanup()  # Ensure cleanup runs if setup fails
            raise

    def check_if_wrong(self, current_question, timeout=3):
        """Check if the answer was wrong by waiting for a new question"""
        try:
            start_time = time()
            while time() - start_time < timeout and self.running:
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
                except StaleElementReferenceException:
                    # Element became stale, retry
                    continue
                except Exception as e:
                    self.update_status(f"Error checking answer: {str(e)}")
                    sleep(0.2)
                    continue
            
            self.update_status("No confirmation of correct answer, assuming wrong")
            return True
        except Exception as e:
            self.update_status(f"Error in check_if_wrong: {str(e)}")
            return True

    def get_openai_response(self, question, choices, previous_wrong_answers=None):
        """Get response from GPT with improved reliability"""
        if not question or not choices:
            self.log("Invalid input for OpenAI request", 'error')
            return None

        try:
            self.update_status("Getting AI response...")
            
            # Build the prompt
            prompt = f"Question: {question}\nChoices:\n"
            for i, choice in enumerate(choices, start=1):
                prompt += f"{i}. {choice}\n"
            
            if previous_wrong_answers:
                prompt += "\nPrevious incorrect answers were: "
                prompt += ", ".join([f"choice {i+1}" for i in previous_wrong_answers])
                prompt += ". Please choose a different answer."
            
            prompt += "\nWhich one is correct? Just respond with the number (1-4)."

            # Make API call
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            
            if not response or not response.choices:
                return None
                
            answer = response.choices[0].message.content.strip()
            if not answer:
                return None
                
            self.update_status(f"AI suggested answer: {answer}")
            return answer

        except Exception as e:
            self.log(f"Error getting OpenAI response: {str(e)}", 'error')
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
                
                # Save final statistics
                self.save_statistics()
                self.save_question_cache()
                
                # Stop the automation
                self.running = False
                
                # Call completion callback if set and not already called
                if self.completion_callback and not self._completion_called:
                    self._completion_called = True
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
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries and self.running:
            try:
                try:
                    self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".question")))
                except TimeoutException:
                    self.update_status("Timeout waiting for question, retrying...")
                    retry_count += 1
                    sleep(1)
                    continue
                    
                question_containers = self.driver.find_elements(By.CSS_SELECTOR, ".question")
                
                if not question_containers:
                    self.update_status("No questions found, retrying...")
                    retry_count += 1
                    sleep(1)
                    continue

                current_container = question_containers[-1]
                
                if current_container == self.last_question_container:
                    try:
                        self.update_status("Waiting for new question...")
                        self.wait.until(EC.staleness_of(self.last_question_container))
                        question_containers = self.driver.find_elements(By.CSS_SELECTOR, ".question")
                        current_container = question_containers[-1]
                    except TimeoutException:
                        self.update_status("Timeout waiting for new question, retrying...")
                        retry_count += 1
                        sleep(1)
                        continue
                
                self.last_question_container = current_container

                # Check for image question first
                if self.is_image_question(current_container):
                    try:
                        choices_div = current_container.find_element(By.CSS_SELECTOR, ".choices")
                        links = choices_div.find_elements(By.TAG_NAME, "a")
                        return "image_question", [], links
                    except Exception as e:
                        self.update_status(f"Error getting image question elements: {str(e)}")
                        retry_count += 1
                        sleep(1)
                        continue
                
                # Check for audio question
                try:
                    audio_button = current_container.find_elements(
                        By.CSS_SELECTOR, "button.playword.ss-highvolume"
                    )
                    if audio_button:
                        if self.solve_audio_question(current_container):
                            return None, None, None
                except Exception as e:
                    self.update_status(f"Error checking audio question: {str(e)}")

                # Get sentence context if available
                sentence_context = ""
                try:
                    sentence_div = current_container.find_element(
                        By.CSS_SELECTOR, ".sentence"
                    )
                    sentence_context = sentence_div.text.strip()
                except Exception:
                    pass  # Sentence context is optional

                # Get choices
                try:
                    choices_div = current_container.find_element(By.CSS_SELECTOR, ".choices")
                    links = choices_div.find_elements(By.TAG_NAME, "a")
                    choices = [link.text.strip() for link in links]

                    if not any(choices):
                        self.update_status("Waiting for choices to load...")
                        retry_count += 1
                        sleep(1)
                        continue
                except Exception as e:
                    self.update_status(f"Error getting choices: {str(e)}")
                    retry_count += 1
                    sleep(1)
                    continue

                # Get question
                try:
                    instructions_div = current_container.find_element(
                        By.CSS_SELECTOR, ".instructions"
                    )
                    question = instructions_div.text.replace("\n", " ").strip()

                    if sentence_context:
                        question = f"{question}\nContext: {sentence_context}"

                    if question == self.last_question_text:
                        self.update_status("Waiting for new question text...")
                        retry_count += 1
                        sleep(1)
                        continue

                    self.last_question_text = question
                    self.update_status(f"Processing question: {question}")
                    return question, choices, links
                except Exception as e:
                    self.update_status(f"Error getting question text: {str(e)}")
                    retry_count += 1
                    sleep(1)
                    continue

            except StaleElementReferenceException:
                self.update_status("Element became stale, retrying...")
                retry_count += 1
                sleep(1)
                continue
            except Exception as e:
                self.update_status(f"Error getting question: {str(e)}")
                retry_count += 1
                sleep(1)
                continue
        
        self.update_status("Failed to get question after multiple attempts")
        return None, None, None

    def set_ready(self):
        self.ready_to_start = True

    def set_completion_callback(self, callback):
        """Set the callback to be called when automation completes"""
        self.completion_callback = callback

    def run(self):
        """Main automation loop with improved terminal UI"""
        try:
            # Initialize browser
            with self._driver_lock:
                if not self.driver:
                    try:
                        self.setup_browser()
                        logging.info("Browser setup successful")
                    except Exception as e:
                        logging.error(f"Failed to initialize browser: {str(e)}")
                        return
                
                try:
                    self.driver.get("https://www.vocabulary.com/account/activities/")
                except Exception as e:
                    logging.error(f"Failed to load initial page: {str(e)}")
                    self.cleanup()
                    return

            # Clear screen and show initial UI
            self.ui.update_display(
                status="Please sign in and select your assignment in the browser window.",
                stats=self.statistics
            )
            
            console.print("\nPress Enter when you're ready to start...")
            input()
            self.ready_to_start = True

            self.ui.update_display(
                status="Starting automation...",
                stats=self.statistics
            )
            
            # Main automation loop
            while self.running:
                try:
                    if not self.running:
                        break

                    # Verify browser is still responsive
                    try:
                        with self._driver_lock:
                            _ = self.driver.current_url
                    except Exception as e:
                        logging.error(f"Browser became unresponsive: {str(e)}")
                        break

                    # Check status updates
                    if self.check_status_updates():
                        continue

                    # Process question
                    result = self.process_question()
                    if not result:
                        sleep(0.5)

                except Exception as e:
                    logging.error(f"Error in main loop: {str(e)}")
                    sleep(1)

        except Exception as e:
            logging.error(f"Critical error in automation: {str(e)}")
        finally:
            self.cleanup()

    def check_status_updates(self):
        """Check for achievements, round completion, or finish state"""
        try:
            with self._driver_lock:
                if self.check_achievement():
                    return True
                if self.check_round_complete():
                    return True
                if self.check_finished():
                    return True
            return False
        except Exception as e:
            self.update_status(f"Error checking status: {str(e)}")
            return False

    def process_question(self):
        """Process a single question with UI updates"""
        try:
            question, choices, links = self.get_question_and_choices()
            if not all([links]):
                return False

            if question == "image_question":
                self.update_status("Processing image question...")
                return self.handle_image_question(self.last_question_container, links)

            self.update_question(question)
            return self.process_answer(question, choices, links)

        except Exception as e:
            logging.error(f"Error processing question: {str(e)}")
            return False

    def process_answer(self, question, choices, links):
        """Process an answer with improved reliability"""
        if not self.running or not question or not choices or not links:
            return False

        try:
            # Try cached answer first
            cached_index = self.get_cached_answer(question, choices)
            if cached_index is not None:
                try:
                    if self.try_answer(cached_index, choices, links):
                        return True
                except Exception as e:
                    self.log(f"Error trying cached answer: {str(e)}", 'error')

            # Try AI-based answer
            wrong_answers = []
            max_retries = 4

            for attempt in range(max_retries):
                if not self.running:
                    return False

                # Get AI response
                try:
                    answer = self.get_openai_response(question, choices, wrong_answers)
                    if not answer:
                        sleep(1)
                        continue

                    match = re.search(r"[1-4]", answer)
                    if not match:
                        self.log(f"No valid choice number found in response: {answer}", 'error')
                        sleep(1)
                        continue

                    choice_index = int(match.group()) - 1
                    if choice_index in wrong_answers:
                        self.log(f"Skipping previously wrong answer: {choice_index + 1}", 'info')
                        sleep(1)
                        continue

                    if not (0 <= choice_index < len(links)):
                        self.log(f"Invalid choice index: {choice_index}", 'error')
                        sleep(1)
                        continue

                    # Try clicking the answer
                    try:
                        links[choice_index].click()
                        self.update_status(f"Selected answer: {choices[choice_index]}")
                    except Exception as e:
                        self.log(f"Error clicking answer: {str(e)}", 'error')
                        sleep(1)
                        continue

                    # Check if answer was correct
                    result = self.check_if_wrong(self.last_question_text)
                    if not result:
                        self.handle_answer_result(self.last_question_text, choices, choice_index, True)
                        return True
                    else:
                        self.handle_answer_result(self.last_question_text, choices, choice_index, False)
                        wrong_answers.append(choice_index)

                except Exception as e:
                    self.log(f"Error processing answer: {str(e)}", 'error')
                    sleep(1)
                    continue

                sleep(1)

            self.log("Exhausted all retry attempts", 'error')
            return False

        except Exception as e:
            self.log(f"Critical error in process_answer: {str(e)}", 'error')
            return False

    def try_answer(self, choice_index, choices, links):
        """Try a single answer with proper error handling"""
        if not (0 <= choice_index < len(links)):
            return False

        try:
            # Try clicking the answer
            try:
                links[choice_index].click()
                self.update_status(f"Selected answer: {choices[choice_index]}")
            except Exception as e:
                self.log(f"Error clicking answer: {str(e)}", 'error')
                return False

            # Check if answer was correct
            result = self.check_if_wrong(self.last_question_text)
            if not result:
                self.handle_answer_result(self.last_question_text, choices, choice_index, True)
                return True
            else:
                self.handle_answer_result(self.last_question_text, choices, choice_index, False)
                return False

        except Exception as e:
            self.log(f"Error trying answer: {str(e)}", 'error')
            return False

    def cleanup(self):
        """Thread-safe cleanup of resources"""
        with self._cleanup_lock:
            if self._cleanup_called:
                return
            self._cleanup_called = True
            
        try:
            # First stop the automation
            self.running = False
            
            # Save data first
            try:
                with self._thread_lock:
                    self.save_statistics()
                    self.save_question_cache()
            except Exception as e:
                self.log(f"Error saving data: {str(e)}", 'error')
            
            # Clean up browser
            with self._driver_lock:
                if hasattr(self, 'driver') and self.driver:
                    try:
                        self.driver.quit()
                    except Exception as e:
                        self.log(f"Error quitting driver: {str(e)}", 'error')
                    finally:
                        self.driver = None
            
            # Force garbage collection
            gc.collect()
            
            # Clean up Chrome processes
            cleanup_chrome_processes()
            
            # Small delay to ensure cleanup completes
            sleep(0.5)
            
        except Exception as e:
            self.log(f"Error during cleanup: {str(e)}", 'error')
        finally:
            self._cleanup_called = False  # Reset flag to allow future cleanup attempts if needed

    def stop(self):
        """Stop automation and clean up"""
        self.running = False
        self.cleanup()

    def __del__(self):
        """Ensure cleanup runs during object destruction"""
        try:
            self.cleanup()
        except Exception as e:
            logging.error(f"Error in destructor: {str(e)}") 