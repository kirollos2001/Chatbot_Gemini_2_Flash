import openai
import os
from packaging import version
import logging
import json
import time
import config
import functions

def check_openai_version():
  required_version = version.parse("1.1.1")
  current_version = version.parse(openai.__version__)
  if current_version < required_version:
    raise ValueError(
        f"Error: OpenAI version {openai.__version__} is less than the required version 1.1.1"
    )
  else:
    logging.info("OpenAI version is compatible.")

def process_tool_calls(client, thread_id, run_id, timeout=60):
    start_time = time.time()

    while True:
        # Break the loop if it exceeds the timeout limit
        if time.time() - start_time > timeout:
            logging.error("❌ Timeout: The run took too long to complete.")
            break

        run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        logging.info(f"🔄 Run status: {run_status.status}")

        if run_status.status == 'completed':
            logging.info("✅ Run completed successfully.")
            break

        elif run_status.status == 'requires_action':
            messages = client.beta.threads.messages.list(thread_id=thread_id)

            # Safely retrieve the latest user message
            user_message = messages.data[0].content[0].text.value if messages.data else ""
            user_message = user_message.lower()
            logging.info(f"📝 User message: {user_message}")

            for tool_call in run_status.required_action.submit_tool_outputs.tool_calls:
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                logging.info(f"🔍 Calling function: {function_name}")

                if function_name == "schedule_viewing":
                    # Add client info to the arguments
                    client_info = config.client_sessions.get(thread_id, {})
                    arguments.update({
                        "client_id": client_info.get("user_id"),
                        "name": client_info.get("name", "Unknown"),
                        "phone": client_info.get("phone", "Not Provided"),
                        "email": client_info.get("email", "Not Provided")
                    })

                    # Check if the user explicitly requested a meeting or provided a time/date
                    if any(keyword in user_message for keyword in ["زووم", "زوم", "اجتماع", "معاينة", "انزل اقابل", "موعد", "لقاء"]) or \
                       any(time_indicator in user_message for time_indicator in ["بكرة","الساعة","الصبح","بليل", "بعد يومين","النهاردة","بعد بكرة","بكره","الوقت", "الضهر", "الصبح", "المساء"]):
                        logging.info("🔄 User requested a meeting, proceeding with scheduling.")
                    else:
                        logging.info("🔄 User did not request a meeting, skipping scheduling.")
                        continue  # Skip scheduling if the user didn't ask for a meeting

                    if not arguments.get("desired_date") or not arguments.get("desired_time") or not arguments.get("meeting_type"):
                        logging.info("🔄 Asking user for date/time before scheduling the meeting.")
                        return {
                            "message": "هل ترغب في تحديد موعد للمعاينة؟ من فضلك اختر التاريخ والوقت وطريقة الاجتماع (زووم أو ميداني)."
                        }

                    arguments['conversation_id'] = thread_id  # Use thread_id as conversation_id

                if hasattr(functions, function_name):
                    try:
                        function_to_call = getattr(functions, function_name)
                        output = function_to_call(arguments)
                        logging.info(f"✅ Function {function_name} executed successfully!")

                        # Submit tool outputs
                        client.beta.threads.runs.submit_tool_outputs(
                            thread_id=thread_id,
                            run_id=run_id,
                            tool_outputs=[{
                                "tool_call_id": tool_call.id,
                                "output": json.dumps(output)
                            }]
                        )
                    except Exception as e:
                        logging.error(f"🚫 Error executing {function_name}: {e}")
                else:
                    logging.warning(f"⚠️ Function {function_name} not found.")

        elif run_status.status in ['failed', 'cancelled', 'expired']:
            logging.error(f"🚨 Run ended with status: {run_status.status}")
            break

        else:
            logging.debug("⏳ Waiting for the run to complete...")
            time.sleep(0.5)
def get_resource_file_ids(client):
  file_ids = []
  resources_folder = 'resources'
  if os.path.exists(resources_folder):
    for filename in os.listdir(resources_folder):
      file_path = os.path.join(resources_folder, filename)
      if os.path.isfile(file_path):
        with open(file_path, 'rb') as file:
          response = client.files.create(file=file, purpose='assistants')
          file_ids.append(response.id)
  return file_ids

