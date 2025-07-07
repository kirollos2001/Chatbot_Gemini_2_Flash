import os
import logging
from flask import Flask, render_template, request, jsonify
import openai
import config
import core_functions
import Assistant
import functions
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import Cache_code
import datetime
from session_store import save_session, get_session
import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool
import json

# Configure logging
logging.basicConfig(level=logging.INFO)

# Configure Gemini
GEMINI_API_KEY = "AIzaSyDsEqJOBhjqHMdqnjTgmFQTvicNTLcMPBE"
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# Define function schemas
schedule_viewing_tool = FunctionDeclaration(
    name="schedule_viewing",
    description="Schedule a property viewing for a client",
    parameters={
        "type": "object",
        "properties": {
            "client_id": {"type": "string"},
            "name": {"type": "string"},
            "phone": {"type": "string"},
            "email": {"type": "string"},
            "property_id": {"type": "string"},
            "conversation_id": {"type": "string"},
            "desired_date": {"type": "string"},
            "desired_time": {"type": "string"},
            "meeting_type": {"type": "string"}
        },
        "required": ["client_id", "property_id", "conversation_id"]
    }
)

search_new_launches_tool = FunctionDeclaration(
    name="search_new_launches",
    description="Search for new real estate launches based on budget and location",
    parameters={
        "type": "object",
        "properties": {
            "budget": {"type": "number"},
            "location": {"type": "string"}
        },
        "required": ["budget", "location"]
    }
)

property_search_tool = FunctionDeclaration(
    name="property_search",
    description="Search for properties based on location, budget, and type",
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string"},
            "budget": {"type": "number"},
            "property_type": {"type": "string"},
            "bedrooms": {"type": "number"},
            "finishing_type": {"type": "string"}
        },
        "required": ["location", "budget", "property_type"]
    }
)

# Register tools
tools = [
    Tool(function_declarations=[schedule_viewing_tool]),
    Tool(function_declarations=[search_new_launches_tool]),
    Tool(function_declarations=[property_search_tool])
]

# Flask App
app = Flask(__name__)
# Load assistant
assistant_id = Assistant.create_assistant()

# Routes
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start", methods=["GET"])
def start_conversation():
    logging.info("📢 Starting a new Gemini conversation session...")
    client_info = {
        "user_id": 77,
        "name": "peter ramzy",
        "email": "test_user@example.com",
        "phone": "01282126288"
    }
    thread_id = f"thread-{datetime.datetime.now().timestamp()}"
    config.client_sessions[thread_id] = client_info
    return jsonify({"thread_id": thread_id})

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    thread_id = data.get("thread_id")
    message = data.get("message", "")

    if not thread_id or not message:
        return jsonify({"error": "Thread ID and message are required."}), 400

    client_info = config.client_sessions.get(thread_id)
    if not client_info:
        return jsonify({"error": "Session expired or thread ID not found."}), 400

    user_id = client_info.get("user_id")

    # Log user message
    functions.log_conversation_to_db(thread_id, user_id, message)

    # Extract preferences and create/update lead
    extracted_info = functions.extract_client_preferences(message)
    functions.create_lead({
        "user_id": user_id,
        "name": client_info.get("name"),
        "phone": client_info.get("phone"),
        "email": client_info.get("email"),
        **extracted_info
    })

    try:
        # Load conversation history
        history_cache = functions.load_from_cache("conversations_cache.json")
        convo = next((c for c in history_cache if c["conversation_id"] == thread_id), None)
        past_messages = convo.get("description", []) if convo else []

        # Format history for Gemini
        formatted_history = [
            {
                "role": "user" if msg["sender"] == "Client" else "model",
                "parts": [msg["message"]]
            }
            for msg in past_messages
        ]

        # System instructions
        system_instructions = {
            "role": "user",
            "parts": [config.assistant_instructions + "\n\n" + "\n\n".join([ex["content"] for ex in config.examples])]
        }

        full_history = [system_instructions] + formatted_history

        # Start chat with tools
        chat = model.start_chat(history=full_history)
        response = chat.send_message(
            message,
            tools=tools
        )

        # Handle function calls
        if response.candidates and response.candidates[0].function_calls:
            function_call = response.candidates[0].function_calls[0]
            function_name = function_call.name
            function_args = function_call.args
            logging.info(f"Function call detected: {function_name} with args {function_args}")

            # Map function name to actual function
            function_map = {
                "schedule_viewing": functions.schedule_viewing,
                "search_new_launches": functions.search_new_launches,
                "property_search": functions.property_search
            }

            if function_name in function_map:
                try:
                    result = function_map[function_name](function_args)
                    # Send function result back to Gemini
                    function_response = chat.send_message(
                        f"Function {function_name} result: {json.dumps(result)}"
                    )
                    bot_reply = function_response.text
                except Exception as e:
                    logging.error(f"Function {function_name} error: {e}")
                    bot_reply = f"Error executing {function_name}: {str(e)}"
            else:
                bot_reply = "Function not recognized."
        else:
            logging.info("No function call detected in response.")
            bot_reply = response.text

    except genai.types.google.api_core.exceptions.ResourceExhausted as e:
        logging.error(f"Quota exceeded: {e}")
        return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
    except Exception as e:
        logging.error(f"❌ Gemini error: {e}")
        return jsonify({"error": str(e)}), 500

    # Log assistant reply
    functions.log_conversation_to_db(thread_id, "bot", bot_reply)

    return jsonify({
        "response": bot_reply,
        "thread_id": thread_id
    })

# Cache initialization
Cache_code.cache_units_from_db()
Cache_code.cache_new_launches_from_db()
Cache_code.cache_devlopers_from_db()

# Scheduler setup
scheduler = BackgroundScheduler()
scheduler.add_job(Cache_code.cache_leads_from_db, 'cron', hour=4)
scheduler.add_job(Cache_code.cache_conversations_from_db, 'cron', hour=4)
scheduler.add_job(Cache_code.sync_leads_to_db, 'cron', hour=3)
scheduler.add_job(Cache_code.sync_conversations_to_db, 'cron', hour=3)
scheduler.start()

# Start app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)