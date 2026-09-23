import os
import sys
import json
import datetime
from google.cloud import bigquery
from google import genai
from google.genai import types

def parse_transcript(input_file_path):
    """
    Parses a customer service transcript using manual extraction rules and outputs a structured JSON file.
    """
    if not os.path.isfile(input_file_path):
        print(f"Error: file not found: {input_file_path}")
        sys.exit(1)

    with open(input_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"Parsing transcript using AI: {input_file_path}")
    ai_result = ai_parse(content)

    os.makedirs("output", exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_file_path))[0]
    output_file = f"output/{base_name}.json"

    try:
        # Validate the JSON before saving
        extracted_data = json.loads(ai_result)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, indent=2)
        print(f"\nSuccessfully wrote parsed JSON to {output_file}")

        # Write results to BigQuery
        write_to_bigquery(extracted_data, content)

    except json.JSONDecodeError:
        print("\nError: AI response was not valid JSON. Saving raw text.")
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(ai_result)


def write_to_bigquery(parsed_data, original_transcript):
    """
    Writes the parsing results, original transcript, and processing logs to BigQuery.
    """
    try:
        # Explicitly set the location to 'US' to avoid 404 location mismatches
        client = bigquery.Client(location="US")
        # Configure dataset and table via environment variables or defaults
        dataset_id = os.environ.get("BQ_DATASET", "support_ops")
        table_id = os.environ.get("BQ_TABLE", "transcript_records")

        # Ensure the dataset exists with an explicit location
        dataset_ref = bigquery.Dataset(client.dataset(dataset_id))
        dataset_ref.location = "US"
        client.create_dataset(dataset_ref, exists_ok=True)
        print(f"Dataset {dataset_id} verified.")

        # Ensure the table exists with the correct schema
        table_ref = client.dataset(dataset_id).table(table_id)
        schema = [
            bigquery.SchemaField("call_id", "STRING"),
            bigquery.SchemaField("parsed_json", "STRING"),
            bigquery.SchemaField("original_transcript", "STRING"),
            bigquery.SchemaField("processed_at", "TIMESTAMP"),
            bigquery.SchemaField("status", "STRING"),
        ]
        table = bigquery.Table(table_ref, schema=schema)
        table = client.create_table(table, exists_ok=True)
        print(f"Table {table_id} verified.")

        row = {
            "call_id": parsed_data.get("call_id", "unknown"),
            "parsed_json": json.dumps(parsed_data),
            "original_transcript": original_transcript,
            "processed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "SUCCESS"
        }

        # Use the fully qualified table ID for the insert call
        errors = client.insert_rows_json(table.reference, [row])
        if errors:
            print(f"BigQuery Insert Errors: {errors}")
        else:
            print(f"Successfully uploaded record to BigQuery: {table.full_table_id}")
    except Exception as e:
        print(f"Failed to write to BigQuery: {e}")

def ai_parse(prompt):
  client = genai.Client(
      vertexai=True,
      api_key=os.environ.get("GOOGLE_CLOUD_API_KEY"),
  )

  si_text1 = """You are an expert transcript parser. 
Extract the following fields into a structured JSON object: 
call_id, date, customer, agent, product, issue, resolution, escalate.
If a field is missing, use an empty string. 'escalate' should be 'yes' or 'no'."""

  model = "gemini-3.6-flash"
  contents = [
    types.Content(
      role="user",
      parts=[types.Part.from_text(text=prompt)
      ]
    )
  ]

  generate_content_config = types.GenerateContentConfig(
    max_output_tokens = 65535,
    system_instruction=[types.Part.from_text(text=si_text1)],
    response_mime_type="application/json",
    thinking_config=types.ThinkingConfig(
      thinking_level="MEDIUM",
    ),
  )

  full_text = ""
  for chunk in client.models.generate_content_stream(
    model = model,
    contents = contents,
    config = generate_content_config,
    ):
    if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
        continue
    print(chunk.text, end="")
    full_text += chunk.text

  return full_text



if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python parse_transcript.py <input_transcript.txt>")
        sys.exit(1)
    parse_transcript(sys.argv[1])