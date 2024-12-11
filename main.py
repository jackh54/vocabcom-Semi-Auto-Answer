import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from time import sleep
from openai import OpenAI
import re


openai_api_key = ''
client = OpenAI(api_key=openai_api_key)


options = uc.ChromeOptions()
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

driver = uc.Chrome(options=options)
wait = WebDriverWait(driver, 10)

last_question_text = ""

def get_openai_response(question, choices):
    prompt = f"Question: {question}\nChoices:\n"
    for i, choice in enumerate(choices, start=1):
        prompt += f"{i}. {choice}\n"
    prompt += "Which one is correct? Just respond with the number (1-4)."

    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    answer = completion.choices[0].message.content.strip()
    print(f"Raw GPT response: {answer}")
    return answer

def check_round_complete():
    try:
        complete_element = driver.find_elements(By.CSS_SELECTOR, "h1 svg.progress-icon")
        if complete_element:
            print("DEBUG: Round complete detected")
            return True
    except Exception as e:
        print(f"DEBUG: Error checking round completion: {str(e)}")
    return False

def reset_and_reload():
    global last_question_text
    print("DEBUG: Resetting variables and reloading page...")
    last_question_text = ""
    driver.get("https://www.vocabulary.com/account/activities/")
    input("Round complete! Please select your assignment and press Enter to continue...")

def get_question_and_choices():
    global last_question_text
    
    if check_round_complete():
        reset_and_reload()
        return None, None, None

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".question")))
    question_containers = driver.find_elements(By.CSS_SELECTOR, ".question")
    print(f"DEBUG: Found {len(question_containers)} total question containers")
    
    if not question_containers:
        print("DEBUG: No question containers found")
        return None, None, None
        
    current_container = question_containers[-1]
    print(f"DEBUG: Using container with class: {current_container.get_attribute('class')}")
    
    try:
        audio_button = current_container.find_elements(By.CSS_SELECTOR, "button.playword.ss-highvolume")
        if audio_button:
            print("DEBUG: Audio question detected - user needs to solve this manually")
            input("This is an audio question. Please solve it manually and press Enter when done...")
            return "RESTART", None, None

        sentence_context = ""
        try:
            sentence_div = current_container.find_element(By.CSS_SELECTOR, ".sentence")
            sentence_context = sentence_div.text.strip()
            print(f"DEBUG: Found sentence context: {sentence_context}")
        except:
            print("DEBUG: No sentence context found")

        choices_div = current_container.find_element(By.CSS_SELECTOR, ".choices")
        links = choices_div.find_elements(By.TAG_NAME, "a")
        choices = [link.text.strip() for link in links]
        
        print(f"DEBUG: Found {len(choices)} choices")
        print(f"DEBUG: Choices text: {choices}")
        
        if all(not choice for choice in choices):
            print("DEBUG: All choices are empty, waiting for content to load...")
            return None, None, None

        instructions_div = current_container.find_element(By.CSS_SELECTOR, ".instructions")
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
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.next.active[aria-label='Next question']"))
        )
        next_button.click()
        print("Clicked next question button")
        sleep(1)
        
    except Exception as e:
        print(f"DEBUG: Error clicking next: {str(e)}")

def main():
    while True: 
        try:

            driver.get("https://www.vocabulary.com/account/activities/")
            input("Please sign in and go to your assignment, then press Enter to continue...")

            while True:
                question, choices, links = get_question_and_choices()

                if question == "RESTART": 
                    print("DEBUG: Restarting after audio question...")
                    last_question_text = ""
                    break  

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

                    if match := re.search(r'[1-4]', answer):
                        correct_choice_index = int(match.group()) - 1  
                        links[correct_choice_index].click()
                        print(f"Clicked on choice #{correct_choice_index + 1}")
                        
                        click_next_question()
                    else:
                        print("Could not determine the correct choice number.")

                    sleep(2)

        except Exception as e:
            print(f"DEBUG: Error in main loop: {str(e)}")
            continue 

if __name__ == "__main__":
    main()