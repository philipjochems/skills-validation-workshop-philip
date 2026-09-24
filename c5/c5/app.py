import streamlit as st
import json
import os
import sys

# Ensure current working directory is in python path for module import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from parse_document import ai_parse, write_to_bigquery, sanitize_user_prompt, sanitize_model_response, GEMINI_SAFETY_SETTINGS

# Page Configuration
st.set_page_config(
    page_title="ADS Unstructured Document Synthesis",
    page_icon="📄",
    layout="centered"
)

st.title("📄 ADS Unstructured Document Synthesis")

st.markdown("""
### About the Alaska Department of Snow
The Alaska Department of Snow (ADS) coordinates plow dispatch, road closures, and public safety alerts during winter storms using a mix of aging backend systems and manual processes.

*Proprietary + Confidential*

**Unstructured Document Synthesis and Secure AI Enablement**
This application allows operators to upload dense operational documents and use Gemini to automatically generate an operational summary, a structured JSON payload, and a public safety risk assessment, while strictly enforcing data isolation and AI safety filters.
""")

# File Uploader
uploaded_file = st.file_uploader("Choose a document (TXT or PDF)...", type=["txt", "pdf"])

if uploaded_file is not None:
    file_extension = uploaded_file.name.split('.')[-1].lower()
    document_content = None
    document_mime_type = None

    if file_extension == "txt":
        raw_document_content = uploaded_file.read().decode("utf-8")
        # Sanitize before previewing in the UI
        document_content = sanitize_user_prompt(raw_document_content)
        document_mime_type = "text/plain"
        st.subheader("Sanitized Document Preview")
        st.text_area("Sanitized Content", document_content, height=180, disabled=True)
    elif file_extension == "pdf":
        import io
        import pypdf
        raw_pdf_bytes = uploaded_file.read()
        raw_pdf_text = ""
        try:
            reader = pypdf.PdfReader(io.BytesIO(raw_pdf_bytes))
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    raw_pdf_text += t + "\n"
        except Exception as e:
            st.error(f"Failed to extract text from PDF: {e}")
        
        # Sanitize before previewing in the UI
        document_content = sanitize_user_prompt(raw_pdf_text)
        document_mime_type = "text/plain"
        st.subheader("Sanitized Document Preview")
        st.text_area("Sanitized Extracted Text", document_content, height=180, disabled=True)
    
    # Save to session state for chat reference
    st.session_state.document_content = document_content
    st.session_state.document_name = uploaded_file.name
    st.session_state.document_mime_type = document_mime_type
    
    # Processing Trigger Action
    if st.button("Parse & Ingest Document", type="primary"):
        with st.spinner("Running Model Armor sanitization & Gemini analysis..."):
            try:
                # Call the core extraction engine
                ai_result = ai_parse(document_content, document_mime_type)
                
                # Validate JSON structuring
                extracted_data = json.loads(ai_result)
                
                st.success("🎉 Extraction successful!")
                st.subheader("Extracted Structured Data (JSON)")
                st.json(extracted_data)
                
                # Stream data into BigQuery
                with st.spinner("Streaming extracted metadata into BigQuery..."):
                    write_to_bigquery(extracted_data, document_content)
                st.info("🚀 Data records successfully uploaded to BigQuery.") 
                
            except json.JSONDecodeError:
                st.error("Failed to parse response: The AI engine did not return valid JSON formatted data.")
            except Exception as e:
                st.error(f"An unexpected error occurred during processing: {e}")
else:
    st.session_state.document_content = None
    st.session_state.document_name = None
    st.session_state.document_mime_type = None

st.markdown("---")
st.subheader("💬 Chat with Gemini")
st.write("Ask questions about the uploaded document or interact with Gemini 3.6 Flash in a multi-turn conversation.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_chat_input := st.chat_input("Type your message here..."):
    # Sanitize user chat input
    sanitized_user_chat_input = sanitize_user_prompt(user_chat_input)
    
    st.session_state.messages.append({"role": "user", "content": sanitized_user_chat_input})
    with st.chat_message("user"):
        st.markdown(sanitized_user_chat_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            from google import genai
            from google.genai import types
            try:
                chat_config = types.GenerateContentConfig(
                    max_output_tokens=2048, # Reasonable max for chat
                    safety_settings=GEMINI_SAFETY_SETTINGS, # Apply consistent safety settings
                )

                client = genai.Client(vertexai=True, api_key=os.environ.get("GOOGLE_CLOUD_API_KEY"))
                contents = []
                
                # Inject the document as context if present
                if st.session_state.get("document_content") is not None:
                    doc_name = st.session_state.get("document_name", "uploaded document")
                    if st.session_state.document_mime_type == "text/plain":
                        doc_part = types.Part.from_text(text=f"Context from '{doc_name}':\n{st.session_state.document_content}\n\n")
                    else:
                        doc_part = types.Part.from_bytes(data=st.session_state.document_content, mime_type=st.session_state.document_mime_type)

                    if st.session_state.messages:
                        # Prepend document context to the first conversation turn
                        first_msg = st.session_state.messages[0]
                        # If the first message is from the user, combine it with the document context
                        if first_msg["role"] == "user":
                            first_parts = [doc_part, types.Part.from_text(text=first_msg["content"])]
                            contents.append(types.Content(role="user", parts=first_parts))
                        else: # If the first message is from the assistant, just add the document context first
                            contents.append(types.Content(role="user", parts=[doc_part]))
                            contents.append(types.Content(role="model", parts=[types.Part.from_text(text=first_msg["content"])]))
                        
                        for m in st.session_state.messages[1:]:
                            api_role = "model" if m["role"] == "assistant" else "user"
                            contents.append(types.Content(role=api_role, parts=[types.Part.from_text(text=m["content"])]))
                else:
                    # If no document is uploaded, just use the chat history
                    for m in st.session_state.messages:
                        api_role = "model" if m["role"] == "assistant" else "user"
                        contents.append(types.Content(role=api_role, parts=[types.Part.from_text(text=m["content"])]))
                
                
                # Stream the response
                full_ai_response = ""
                message_placeholder = st.empty()
                for chunk in client.models.generate_content_stream(model="gemini-3.6-flash", contents=contents, config=chat_config):
                    full_ai_response += chunk.text
                    message_placeholder.markdown(full_ai_response + "▌") # Add blinking cursor

                # Sanitize model chat response
                final_ai_response = sanitize_model_response(full_ai_response)

                message_placeholder.markdown(final_ai_response)
                st.session_state.messages.append({"role": "assistant", "content": final_ai_response})
            except Exception as e:
                st.error(f"An error occurred: {e}")