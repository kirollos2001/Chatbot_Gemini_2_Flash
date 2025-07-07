import os
import logging
from flask import Flask, render_template, request, jsonify
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

# Configure logging
logging.basicConfig(level=logging.INFO)

# Configure Gemini
GEMINI_API_KEY = "AIzaSyDsEqJOBhjqHMdqnjTgmFQTvicNTLcMPBE"
genai.configure(api_key=GEMINI_API_KEY)

# Define Function Declarations for Gemini
schedule_viewing_declaration = genai.protos.FunctionDeclaration(
    name="schedule_viewing",
    description="جدولة اجتماع معاينة مع العميل. يجب سؤال العميل عن التاريخ، الوقت، ونوع الاجتماع (زووم أو ميداني).",
    parameters={
        "type": "object",
        "properties": {
            "client_id": {"type": "integer", "description": "كود العميل"},
            "name": {"type": "string", "description": "اسم العميل"},
            "phone": {"type": "string", "description": "رقم هاتف العميل"},
            "property_id": {"type": "integer", "description": "كود العقار"},
            "desired_date": {"type": "string", "description": "تاريخ الاجتماع"},
            "desired_time": {"type": "string", "description": "وقت الاجتماع"},
            "meeting_type": {"type": "string", "description": "نوع الاجتماع (zoom أو visit)", "enum": ["zoom", "visit"]},
            "email": {"type": "string", "description": "البريد الإلكتروني للعميل"},
            "conversation_id": {"type": "string", "description": "كود المحادثة"}
        },
        "required": ["client_id", "name", "phone", "property_id", "desired_date", "desired_time", "meeting_type", "email", "conversation_id"]
    }
)

contact_declaration = genai.protos.FunctionDeclaration(
    name="contact_us",
    description="التواصل مع خدمة العملاء لجدولة معاينة عقار أو الاستفسار عن العقارات.",
    parameters={
        "type": "object",
        "properties": {
            "property_id": {"type": "integer", "description": "كود العقار"},
            "desired_date": {"type": "string", "description": "التاريخ المطلوب"},
            "desired_time": {"type": "string", "description": "الوقت المطلوب"},
            "email": {"type": "string", "description": "البريد الإلكتروني"}
        },
        "required": ["property_id", "desired_date", "desired_time", "email"]
    }
)

create_lead_declaration = genai.protos.FunctionDeclaration(
    name="create_lead",
    description="إنشاء عميل جديد بمعلوماته وتفضيلاته.",
    parameters={
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "كود العميل"},
            "name": {"type": "string", "description": "اسم العميل"},
            "phone": {"type": "string", "description": "رقم الهاتف"},
            "email": {"type": "string", "description": "البريد الإلكتروني"},
            "property_preferences": {"type": "string", "description": "تفضيلات العقار"},
            "budget": {"type": "number", "description": "الميزانية"},
            "location": {"type": "string", "description": "الموقع المفضل"},
            "property_type": {"type": "string", "description": "نوع العقار"},
            "bedrooms": {"type": "integer", "description": "عدد الغرف"},
            "bathrooms": {"type": "integer", "description": "عدد الحمامات"}
        },
        "required": ["client_id", "name", "phone", "location", "property_type"]
    }
)

property_search_declaration = genai.protos.FunctionDeclaration(
    name="property_search",
    description="البحث عن العقارات بناءً على تفضيلات العميل.",
    parameters={
        "type": "object",
        "properties": {
            "budget": {"type": "integer", "description": "الميزانية"},
            "location": {"type": "string", "description": "الموقع"},
            "property_type": {"type": "string", "description": "نوع العقار"},
            "bedrooms": {"type": "integer", "description": "عدد الغرف"},
            "bathrooms": {"type": "integer", "description": "عدد الحمامات"},
            "compound": {"type": "string", "description": "اسم الكمبوند"},
            "finishing_type": {"type": "string", "description": "نوع التشطيب"}
        },
        "required": ["budget", "location", "property_type"]
    }
)

search_new_launches_declaration = genai.protos.FunctionDeclaration(
    name="search_new_launches",
    description="البحث عن المشاريع العقارية الجديدة بناءً على وصف أو حالة العقار.",
    parameters={
        "type": "object",
        "properties": {
            "search_term": {"type": "string", "description": "مصطلح البحث"},
            "status": {"type": "string", "description": "حالة العقار"}
        },
        "required": ["search_term"]
    }
)

# Combine all function declarations into a Tool
tools = genai.protos.Tool(function_declarations=[
    schedule_viewing_declaration,
    contact_declaration,
    create_lead_declaration,
    property_search_declaration,
    search_new_launches_declaration
])

# Initialize the model with tools
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash',
    tools=[tools],
    generation_config={"temperature": 0.2}
)

# Flask App
app = Flask(__name__)

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
    if not request.is_json:
        return jsonify({"error": "Request must be JSON."}), 400

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
        # Load conversation history from cache
        history_cache = functions.load_from_cache("conversations_cache.json")
        convo = next((c for c in history_cache if c["conversation_id"] == thread_id), None)
        past_messages = convo.get("description", []) if convo else []

        # Format messages for Gemini
        formatted_history = [
            {
                "role": "user" if msg["sender"] == "Client" else "assistant",
                "parts": [msg["message"]]
            }
            for msg in past_messages
        ]

        # Prepend system instructions
        system_instructions = {
            "role": "user",
            "parts": [config.assistant_instructions + "\n\n" + "\n\n".join([ex["content"] for ex in config.examples])]
        }
        full_history = [system_instructions] + formatted_history + [{"role": "user", "parts": [message]}]

        # Generate content
        response = model.generate_content(full_history)

        # Check for function calls
        if response.candidates and response.candidates[0].function_calls:
            function_call = response.candidates[0].function_calls[0]
            function_name = function_call.name
            arguments = function_call.args

            # Map function names to implementations
            function_map = {
                "schedule_viewing": functions.schedule_viewing,
                "contact_us": functions.contact_us,
                "create_lead": functions.create_lead,
                "property_search": functions.property_search,
                "search_new_launches": functions.search_new_launches
            }

            if function_name in function_map:
                result = function_map[function_name](arguments)
                bot_reply = result.get("message", "Function executed successfully.")
                functions.log_conversation_to_db(thread_id, "bot", bot_reply)
                return jsonify({
                    "response": bot_reply,
                    "thread_id": thread_id,
                    "function_result": result
                })
            else:
                logging.error(f"Unknown function: {function_name}")
                return jsonify({"error": f"Unknown function: {function_name}"}), 400
        else:
            # No function call; return text response
            bot_reply = response.text
            functions.log_conversation_to_db(thread_id, "bot", bot_reply)
            return jsonify({
                "response": bot_reply,
                "thread_id": thread_id
            })

    except Exception as e:
        logging.error(f"❌ Gemini error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# Cache initialization
Cache_code.cache_units_from_db()
Cache_code.cache_new_launches_from_db()
Cache_code.cache_developers_from_db()  # Corrected typo

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