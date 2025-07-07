import os
import json
import config

def create_assistant(client=None):
    assistant_file_path = os.path.join(os.getcwd(), 'assistant.json')

    if os.path.exists(assistant_file_path):
        with open(assistant_file_path, 'r') as file:
            assistant_data = json.load(file)
            assistant_id = assistant_data['assistant_id']
            print("Loaded existing assistant ID.")
    else:
        assistant_id = "gemini-flash-001"
        print(f"Using Gemini Flash Model: {assistant_id}")

        with open(assistant_file_path, 'w') as file:
            json.dump({'assistant_id': assistant_id}, file)

    return assistant_id
