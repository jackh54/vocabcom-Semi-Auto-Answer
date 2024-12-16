import json
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from time import sleep
from openai import OpenAI
import re

with open('config.json', 'r') as config_file:
    config = json.load(config_file)

openai_api_key = config["openai_api_key"]
client = OpenAI(api_key=openai_api_key)

options = uc.ChromeOptions()
for option, value in config["chrome_options"].items():
    if isinstance(value, bool) and value:
        options.add_argument(f"--{option.replace('_', '-')}")
    elif isinstance(value, str):
        options.add_argument(f"--{option.replace('_', '-')}={value}")

driver = uc.Chrome(options=options)
wait = WebDriverWait(driver, 10)

last_question_text = ""
last_question_container = None
last_input_field = None

statistics = {
    "correct_answers": 0,
    "wrong_answers": 0,
    "achievements": 0
}


def save_statistics():
    with open('statistics.json', 'w') as stats_file:
        json.dump(statistics, stats_file, indent=4)


def get_openai_response(question, choices):
    prompt = f"Question: {question}\nChoices:\n"
    for i, choice in enumerate(choices, start=1):
        prompt += f"{i}. {choice}\n"
    prompt += "Which one is correct? Just respond with the number (1-4)."

    completion = client.chat.completions.create(
        model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}]
    )

    answer = completion.choices[0].message.content.strip()
    print(f"Raw GPT response: {answer}")
    return answer


def check_round_complete():
    try:
        complete_element = driver.find_elements(
            By.CSS_SELECTOR, "h1 svg.progress-icon")
        if complete_element:
            print("DEBUG: Round complete detected")
            return True
    except Exception as e:
        print(f"DEBUG: Error checking round completion: {str(e)}")
    return False


def reset_and_reload():
    global last_question_text, last_question_container, last_input_field
    print("DEBUG: Resetting variables and reloading page...")
    last_question_text = ""
    last_question_container = None
    last_input_field = None
    print("Round complete! Continuing")


def check_and_click_next_if_achievement():
    try:
        achievement_elements = driver.find_elements(
            By.CSS_SELECTOR, ".hero.with-header-padding")
        for achievement_element in achievement_elements:
            is_processed = driver.execute_script(
                "return arguments[0].getAttribute('data-processed');",
                achievement_element)
            if not is_processed:
                print("DEBUG: Achievement detected")
                statistics["achievements"] += 1
                save_statistics()
                next_button = wait.until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR,
                         "button.next.active[aria-label='Next question']"))
                )
                next_button.click()
                print("DEBUG: Clicked next - achievement")
                sleep(1)
                driver.execute_script(
                    "arguments[0].setAttribute('data-processed', 'true');",
                    achievement_element)
                return True
    except Exception as e:
        print(f"DEBUG: No achievement element found: {str(e)}")
    return False


def check_if_finished():
    try:
        finished_element = driver.find_element(
            By.CSS_SELECTOR, ".practiceComplete.activity-summary")
        if finished_element:
            print("Finished the list!")
            input("Press Enter to restart the loop.")
            return True
    except Exception as e:
        print(f"DEBUG: No finished element found: {str(e)}")
    return False


def get_question_and_choices():
    global last_question_text, last_question_container

    if check_round_complete():
        reset_and_reload()
        click_next_question()
        return None, None, None

    if check_and_click_next_if_achievement():
        return None, None, None

    if check_if_finished():
        return None, None, None

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".question")))
    question_containers = driver.find_elements(By.CSS_SELECTOR, ".question")
    print(f"DEBUG: Found {len(question_containers)} total question containers")

    if not question_containers:
        print("DEBUG: No question containers found")
        return None, None, None

    current_container = question_containers[-1]

    if current_container == last_question_container:
        print(
            "DEBUG: Current container is same as last one, waiting for new"
        )
        wait.until(EC.staleness_of(last_question_container))
        question_containers = driver.find_elements(
            By.CSS_SELECTOR, ".question")
        current_container = question_containers[-1]

    last_question_container = current_container
    print(
        "DEBUG: Using container with class: "
        f"{current_container.get_attribute('class')}"
    )

    try:
        audio_button = current_container.find_elements(
            By.CSS_SELECTOR, "button.playword.ss-highvolume"
        )
        if audio_button:
            print("DEBUG: Audio question detected - solving automatically")
            solve_audio_question(current_container)
            return None, None, None

        sentence_context = ""
        try:
            sentence_div = current_container.find_element(
                By.CSS_SELECTOR, ".sentence")
            sentence_context = sentence_div.text.strip()
            print(f"DEBUG: Found sentence context: {sentence_context}")
        except BaseException:
            print("DEBUG: No sentence context found")

        choices_div = current_container.find_element(
            By.CSS_SELECTOR, ".choices")
        links = choices_div.find_elements(By.TAG_NAME, "a")
        choices = [link.text.strip() for link in links]

        print(f"DEBUG: Found {len(choices)} choices")
        print(f"DEBUG: Choices text: {choices}")

        if all(not choice for choice in choices):
            print("DEBUG: All choices are empty, waiting for content to load")
            return None, None, None

        instructions_div = current_container.find_element(
            By.CSS_SELECTOR, ".instructions"
        )
        question = instructions_div.text.replace("\n", " ").strip()

        if sentence_context:
            question = f"{question}\nContext: {sentence_context}"

        print(f"DEBUG: Raw question text: '{question}'")

        last_question_text = question
        return question, choices, links

    except Exception as e:
        print(f"DEBUG: Error getting question/choices: {str(e)}")
        return None, None, None


def click_next_question():
    sleep(1)
    try:
        next_button = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR,
                 "button.next.active[aria-label='Next question']")
            )
        )
        next_button.click()
        print("Clicked next question button")
        sleep(1)

    except Exception as e:
        print(f"DEBUG: Error clicking next: {str(e)}")


def solve_audio_question(current_container):
    global last_input_field
    try:
        sentence_div = current_container.find_element(
            By.CSS_SELECTOR, "div.sentence.complete"
        )
        print(
            "DEBUG: Located sentence div: "
            f"{sentence_div.get_attribute('outerHTML')}"
        )

        word = driver.execute_script(
            "return arguments[0].querySelector('strong').innerText;",
            sentence_div
        )
        print(f"DEBUG: Extracted word using JavaScript: {word}")

        if not word:
            print("DEBUG: Extracted word is empty")
            return

        input_field = current_container.find_element(
            By.CSS_SELECTOR, "input.wordspelling"
        )

        if input_field == last_input_field:
            print(
                "DEBUG: Input field is same as the last one, waiting for new"
            )
            wait.until(EC.staleness_of(last_input_field))
            input_field = current_container.find_element(
                By.CSS_SELECTOR, "input.wordspelling"
            )

        last_input_field = input_field
        input_field.clear()
        input_field.send_keys(word + Keys.RETURN)
        print("DEBUG: Typed the word and pressed Enter in the input field")

        next_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.next"))
        )
        next_button.click()
        print("DEBUG: Clicked the 'Next' button")

    except Exception as e:
        print(f"An error occurred: {e}")


def main():
    while True:
        try:
            driver.get("https://www.vocabulary.com/account/activities/")
            input(
                "Sign in and click your assignment and press enter."
            )

            while True:
                question, choices, links = get_question_and_choices()

                if question is None or choices is None or links is None:
                    print("Failed to find new question or choices")
                    sleep(1)
                    continue

                if len(links) == 0:
                    print("Choices do not exist.")
                else:
                    print("Choices exist.")
                    for i, choice in enumerate(choices, start=1):
                        print(f"Choice #{i}: {choice}")

                    answer = get_openai_response(question, choices)
                    print(f"OpenAI suggests: {answer}")

                    if match := re.search(r"[1-4]", answer):
                        correct_choice_index = int(match.group()) - 1
                        links[correct_choice_index].click()
                        print(f"Clicked on choice #{correct_choice_index + 1}")

                        statistics["correct_answers"] += 1
                        save_statistics()

                        click_next_question()
                    else:
                        print("Could not determine the correct choice number.")
                        statistics["wrong_answers"] += 1
                        save_statistics()

                    sleep(2)

        except Exception as e:
            print(f"DEBUG: Error in main loop: {str(e)}")
            continue


if __name__ == "__main__":
    main()
