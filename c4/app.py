import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="AI Chatbot", page_icon="🤖")
st.title("AI Conversation Specialist")

# Initialize the Gemini client in session state so it persists across reruns
if "client" not in st.session_state:
    st.session_state.client = genai.Client(vertexai=True)

# Streamlit maintains history in session_state to prevent losing context on refresh
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display past conversation history using Streamlit's chat components
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Accept user input
if user_input := st.chat_input("Type your message here..."):
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(user_input)
    
    # Add user message to local history tracker
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Reconstruct the conversation history into the SDK's expected format
    api_history = []
    for msg in st.session_state.messages:
        role = "user" if msg["role"] == "user" else "model"
        api_history.append(
            types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])])
        )

    # Configuration definitions matching your main script
    model_id = "gemini-3.6-flash"
    si_text1 = "You are an conversation specialist. Respond in natural language."

    tools = [
        types.Tool(google_search=types.GoogleSearch()),
        types.Tool(google_maps=types.GoogleMaps()),
    ]
    tool_config = types.ToolConfig(
        retrieval_config=types.RetrievalConfig(),
    )

    generate_content_config = types.GenerateContentConfig(
        max_output_tokens=65535,
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_MEDIUM_AND_ABOVE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_MEDIUM_AND_ABOVE")
        ],
        tools=tools,
        tool_config=tool_config,
        system_instruction=[types.Part.from_text(text=si_text1)],
    )

    # Display assistant response in chat message container with streaming UI
    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""
        
        # Request the streaming response from Gemini
        response_stream = st.session_state.client.models.generate_content_stream(
            model=model_id,
            contents=api_history,
            config=generate_content_config,
        )
        
        for chunk in response_stream:
            if chunk.text:
                full_response += chunk.text
                response_placeholder.markdown(full_response + "▌")
        
        response_placeholder.markdown(full_response)
    
    # Add assistant response to local history tracker
    st.session_state.messages.append({"role": "assistant", "content": full_response})