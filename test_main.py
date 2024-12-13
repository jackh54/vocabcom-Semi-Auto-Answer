import pytest
from unittest.mock import patch, MagicMock
from main import get_openai_response, check_round_complete, reset_and_reload, get_question_and_choices, click_next_question, solve_audio_question

@pytest.fixture
def mock_driver():
    with patch('main.driver') as mock_driver:
        yield mock_driver

@pytest.fixture
def mock_openai():
    with patch('main.client') as mock_client:
        yield mock_client

@patch('builtins.input', return_value='')
def test_reset_and_reload(mock_input, mock_driver):
    reset_and_reload()
    mock_driver.get.assert_called_with("https://www.vocabulary.com/account/activities/") 

def test_solve_audio_question(mock_driver):
    from selenium.webdriver.common.keys import Keys
    mock_container = MagicMock()
    mock_driver.execute_script.return_value = "word"
    solve_audio_question(mock_container)
    mock_driver.execute_script.assert_called_once()
    mock_container.find_element.return_value.send_keys.assert_called_with("word" + Keys.RETURN)

def test_get_openai_response(mock_openai):
    mock_openai.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="1"))])
    question = "What is the capital of France?"
    choices = ["Paris", "London", "Berlin", "Madrid"]
    response = get_openai_response(question, choices)
    assert response == "1"

def test_check_round_complete(mock_driver):
    mock_driver.find_elements.return_value = [MagicMock()]
    assert check_round_complete() == True

    mock_driver.find_elements.return_value = []
    assert check_round_complete() == False