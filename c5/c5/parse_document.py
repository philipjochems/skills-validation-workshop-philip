import os
import sys
import json
import datetime
import logging
import google.cloud.logging
from google.cloud import bigquery
from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import NotFound
from google.cloud import modelarmor_v1
from google import genai
from google.genai import types

# Initialize Cloud Logging and attach it to the standard Python logging framework
log_client = google.cloud.logging.Client()
log_client.setup_logging()
logging.basicConfig(level=logging.INFO)


def _api_sanitize_input(user_prompt: str):
  project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-60ac594de936")
  location_id = "us"
  template_id = "philip-model-armor-template"

  # Create the Model Armor client
  client = modelarmor_v1.ModelArmorClient(
      transport="rest",
      client_options=ClientOptions(
          api_endpoint=f"modelarmor.{location_id}.rep.googleapis.com"
      ),
  )


  # Initialize request argument(s)
  user_prompt_data = modelarmor_v1.DataItem(text=user_prompt)

  # Prepare request for sanitizing the defined prompt
  request = modelarmor_v1.SanitizeUserPromptRequest(
      name=f"projects/{project_id}/locations/{location_id}/templates/{template_id}",
      user_prompt_data=user_prompt_data,
  )

  # Sanitize the user prompt
  response = client.sanitize_user_prompt(request=request)

  return response

def _api_sanitize_model_response(model_response: str):
  project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-60ac594de936")
  location_id = "us"
  template_id = "philip-model-armor-template"

  # Create the Model Armor client
  client = modelarmor_v1.ModelArmorClient(
      transport="rest",
      client_options=ClientOptions(
          api_endpoint=f"modelarmor.{location_id}.rep.googleapis.com"
      ),
  )

  # Initialize request argument(s)
  model_response_data = modelarmor_v1.DataItem(text=model_response)

  # Prepare request for sanitizing model response.
  request = modelarmor_v1.SanitizeModelResponseRequest(
      name=f"projects/{project_id}/locations/{location_id}/templates/{template_id}",
      model_response_data=model_response_data,
  )

  # Sanitize the model response.
  response = client.sanitize_model_response(request=request)
  return response

def parse_document(input_file_path):
    """
    Parses a customer service document using manual extraction rules and outputs a structured JSON file.
    """
    
    if not os.path.isfile(input_file_path):
        logging.error(f"Error: file not found: {input_file_path}")
        sys.exit(1)

    # For CLI, assume text files for now. Streamlit will handle PDF.
    with open(input_file_path, 'r', encoding='utf-8') as f: 
        content = f.read() 

    ai_result = ai_parse(content, "text/plain") # CLI always processes text
    logging.info(f"Parsing document using AI: {input_file_path}")
    os.makedirs("output", exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_file_path))[0]
    output_file = f"output/{base_name}.json"

    try:
        # Validate the JSON before saving
        extracted_data = json.loads(ai_result)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, indent=2)
        logging.info(f"Successfully wrote parsed JSON to {output_file}")

        # Write results to BigQuery
        write_to_bigquery(extracted_data, content) # 'content' is always string here for CLI

    except json.JSONDecodeError:
        logging.error("Error: AI response was not valid JSON. Saving raw text.")
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(ai_result)


def write_to_bigquery(parsed_data, original_document):
    """
    Writes the parsing results, original document, and processing logs to BigQuery.
    """
    try:
        # Explicitly set the location to 'US' to avoid 404 location mismatches
        client = bigquery.Client(location="US")
        # Configure dataset and table via environment variables or defaults
        dataset_id = os.environ.get("BQ_DATASET", "support_ops")
        table_id = os.environ.get("BQ_TABLE", "document_records")

        # Ensure the dataset exists with an explicit location
        dataset_ref = bigquery.Dataset(client.dataset(dataset_id))
        dataset_ref.location = "US"
        client.create_dataset(dataset_ref, exists_ok=True)
        logging.info(f"Dataset {dataset_id} verified.")

        # Ensure the table exists with the correct schema
        table_ref = client.dataset(dataset_id).table(table_id)
        schema = [
            bigquery.SchemaField("call_id", "STRING"),
            bigquery.SchemaField("parsed_json", "STRING"),
            bigquery.SchemaField("original_document", "STRING"),
            bigquery.SchemaField("processed_at", "TIMESTAMP"),
            bigquery.SchemaField("status", "STRING"),
        ]
        try:
            table = client.get_table(table_ref)
            logging.info(f"Table {table_id} verified.")
        except NotFound:
            table = bigquery.Table(table_ref, schema=schema)
            table = client.create_table(table)
            logging.info(f"Table {table_id} created.")

        # Safely extract call_id from top level or nested within structured_payload
        call_id = parsed_data.get("call_id")
        if not call_id and isinstance(parsed_data.get("structured_payload"), dict):
            call_id = parsed_data.get("structured_payload").get("call_id")

        row = {
            "call_id": call_id or "unknown",
            "parsed_json": json.dumps(parsed_data),
            "original_document": original_document,
            "processed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "SUCCESS"
        }
        
        # Handle original_document for BigQuery: ensure it's a string
        if isinstance(original_document, bytes):
            row["original_document"] = f"PDF content (length: {len(original_document)} bytes, not stored directly in BigQuery)"

        # Use the fully qualified table ID for the insert call
        errors = client.insert_rows_json(table.reference, [row])
        if errors:
            logging.error(f"BigQuery Insert Errors: {errors}")
        else:
            logging.info(f"Successfully uploaded record to BigQuery: {table.full_table_id}")
    except Exception as e:
        logging.error(f"Failed to write to BigQuery: {e}")

def _model_armor_sanitize(text: str, is_prompt: bool = True) -> str:
    """Helper to sanitize text in chunks using Model Armor to avoid size limits."""
    chunk_size = 4000  # Model Armor character limit per request

    # Process text in chunks to stay within Model Armor limits
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    sanitized_segments = []
    
    for chunk in chunks:
        try:
            data = _api_sanitize_input(chunk)
            
            # if is_prompt:
            #     response = _api_sanitize_input(chunk)
            #     # Security Control: Immediate halt if Model Armor triggers a BLOCK action
            #     if response.invocation_result.invocation_state == modelarmor_v1.InvocationResult.InvocationState.BLOCK:
            #         logging.warning("Model Armor blocked the user prompt/document.")
            #         #return "[REDACTED - CONTENT BLOCKED BY SAFETY POLICY]"
            #     data = response.sanitization_metadata.sanitized_user_prompt_data
            # else:
            #     response = _api_sanitize_model_response(chunk)
            #     # Security Control: Immediate halt if Model Armor triggers a BLOCK action
            #     if response.invocation_result.invocation_state == modelarmor_v1.InvocationResult.InvocationState.BLOCK:
            #         logging.warning("Model Armor blocked the model response.")
            #         #return "[REDACTED - CONTENT BLOCKED BY SAFETY POLICY]"
            #     data = response.sanitization_metadata.sanitized_model_response_data
        except Exception as e:
            logging.error(f"Model Armor request failed: {e}")
         
            data = None

        # Collect sanitized text segment, or fallback to original if sanitization fails
        if data and hasattr(data, 'text'):
            sanitized_segments.append(data.text)
        else:
            sanitized_segments.append(chunk)
            
    return "".join(sanitized_segments)

def sanitize_user_prompt(user_prompt: str) -> str:
    return _model_armor_sanitize(user_prompt, is_prompt=True)

def sanitize_model_response(model_response: str):
    return _model_armor_sanitize(model_response, is_prompt=False)

GEMINI_SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_MEDIUM_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_MEDIUM_AND_ABOVE")
]

def ai_parse(document_content, document_mime_type):
  client = genai.Client(
      vertexai=True,
  )

  si_text1 = """You are an expert document analyst and safety officer. 
Analyze the provided document and automatically generate a structured JSON object containing exactly the following top-level fields:
- operational_summary: A concise, clear textual summary of the operations, events, and context described in the document.
- structured_payload: A nested JSON object capturing all relevant metadata, attributes, key-value pairs, and entities found dynamically in the text (such as names, dates, call_ids, product names, metrics).
- public_safety_risk_assessment: A rigorous text evaluation detailing any public safety concerns, threats, liabilities, or hazardous signals detected. If no risks are found, populate this with 'low risk'."""
  
  # 1. Sanitize the user prompt first using Model Armor
  # Model Armor's sanitize_user_prompt expects a string.
  # We only apply it if the input document is text.
  if document_mime_type == "text/plain":
      sanitized_document_part = sanitize_user_prompt(document_content)
      logging.info(f"Original text document length: {len(document_content)}, Sanitized text document length: {len(sanitized_document_part)}")
      contents_part = types.Part.from_text(text=sanitized_document_part)
  elif document_mime_type == "application/pdf":
      import io
      import pypdf
      pdf_text = ""
      try:
          reader = pypdf.PdfReader(io.BytesIO(document_content))
          for page in reader.pages:
              t = page.extract_text()
              if t:
                  pdf_text += t + "\n"
      except Exception as e:
          logging.error(f"Failed to extract text from PDF: {e}")
      pdf_text = sanitize_user_prompt(pdf_text)
      contents_part = types.Part.from_text(text=pdf_text)
  else:
      raise ValueError(f"Unsupported document MIME type: {document_mime_type}")

  model = "gemini-3.6-flash"
  contents = [types.Content(role="user", parts=[contents_part])]

  generate_content_config = types.GenerateContentConfig(
    max_output_tokens = 65535,
    system_instruction=[types.Part.from_text(text=si_text1)],
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(
      thinking_level="MEDIUM",
    ),
    safety_settings = GEMINI_SAFETY_SETTINGS,
  )

  full_text = ""
  for chunk in client.models.generate_content_stream(
    model = model,
    contents = contents,
    config = generate_content_config,
    ):
    if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
        continue
    full_text += chunk.text

  # 2. Sanitize the generated model response before returning it
  final_text = sanitize_model_response(full_text)
  
  logging.info(f"Original AI response length: {len(full_text)}, Sanitized AI response length: {len(final_text)}")
  return final_text


if __name__ == "__main__":
    if len(sys.argv) != 2:
        logging.error("Usage: python parse_document.py <input_document.txt>")
        sys.exit(1) # Corrected: ensure closing parenthesis is ')'
    try:
        parse_document(sys.argv[1])
    finally:
        for handler in logging.root.handlers[:]:
            handler.close()
            logging.root.removeHandler(handler)
