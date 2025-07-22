from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
import requests
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
import speech_recognition as sr
from gtts import gTTS # Google Text-to-Speech
import io
import json
import pyaudio  
from pydub import AudioSegment

# Load environment variables
load_dotenv()
app = Flask(__name__)

# --- Database Configuration ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define Message Model for Persistent Storage
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_input = db.Column(db.Text, nullable=False)
    ai_response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
    session_id = db.Column(db.String(255), nullable=True) # To group messages by session

    def __repr__(self):
        return f'<Message {self.id}>'

# Create database tables (run once)
with app.app_context():
    db.create_all()

# --- Gemini API Configuration ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file. Please set it.")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
headers = {"Content-Type": "application/json"}

# --- In-memory store for current conversation history (for demonstration within a session) ---
# A real app might use a more sophisticated session management for multi-user.
# For simplicity, we'll clear it on page reload, but messages are saved to DB.
conversation_history_in_memory = {} # {session_id: [{"role": "user", ...}, {"role": "model", ...}]}

# --- RAG Data (Simple in-memory for demo) ---
study_materials = []
def load_study_materials(filepath="data/study_materials.txt"):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.readlines()
    except FileNotFoundError:
        print(f"Warning: Study materials file not found at {filepath}. RAG will not function.")
        return []

study_materials = load_study_materials()

# Helper function to generate a unique session ID
import uuid
def get_session_id():
    # In a real application, this would come from Flask session or user login
    # For this demo, we'll use a simple approach for new sessions.
    if 'session_id' not in request.cookies:
        return str(uuid.uuid4())
    return request.cookies.get('session_id')


import json # Ensure json is imported at the top

@app.route("/")
def index():
    session_id = get_session_id()

    global conversation_history_in_memory
    if session_id not in conversation_history_in_memory:
        conversation_history_in_memory[session_id] = [] # Initialize for this session_id

    # Load persistent chat history for the current session
    past_messages = Message.query.filter_by(session_id=session_id).order_by(Message.timestamp).all()
    history_for_template = []
    for msg in past_messages:
        history_for_template.append({"role": "user", "text": msg.user_input})
        history_for_template.append({"role": "model", "text": msg.ai_response})
        # Also rebuild in-memory history for RAG and context
        # Make sure to not add the dummy "Hello MindMate..." to DB history,
        # only the real interaction history.
        conversation_history_in_memory[session_id].append({"role": "user", "parts": [{"text": msg.user_input}]})
        conversation_history_in_memory[session_id].append({"role": "model", "parts": [{"text": msg.ai_response}]})

    # Now that history_for_template is populated, render the template
    rendered_html = render_template("index.html", initial_history=history_for_template)

    # Create the response object and set the cookie
    response = app.make_response(rendered_html)
    response.set_cookie('session_id', session_id)

    return response


@app.route("/chat", methods=["POST"])
def chat():
    session_id = request.cookies.get('session_id')
    if not session_id or session_id not in conversation_history_in_memory:
        # If session_id is missing or history not initialized, redirect to home
        return jsonify({"response": "Please refresh the page to start a new session."}), 400

    current_conversation_history = conversation_history_in_memory[session_id]
    user_input = request.json.get("message")
    chat_type = request.json.get("chat_type", "mental_health") # 'mental_health' or 'study_buddy'

    prompt_text = user_input
    system_instruction = ""
    rag_context = ""

    if chat_type == "mental_health":
        if not current_conversation_history:
            system_instruction = "You are a compassionate mental health assistant named MindMate. Start the conversation with a warm greeting and ask how the user is feeling. Respond with empathy and care."
            prompt_text = f"{system_instruction} User's first message: {user_input}"
    elif chat_type == "study_buddy":
        # Implement RAG here: retrieve relevant context from study_materials
        # For a simple demo, we'll just check if keywords from user_input are in study materials
        # In a real RAG, you'd use embeddings and vector search.
        relevant_docs = [doc for doc in study_materials if any(word.lower() in doc.lower() for word in user_input.split())]
        rag_context = "\n".join(relevant_docs[:3]) # Take top 3 relevant lines
        if rag_context:
            system_instruction = "You are an AI Study Buddy. Provide factual and concise answers based on the provided study materials and your general knowledge. If the answer is not in the provided context, state that. Respond politely."
            prompt_text = f"{system_instruction}\n\nStudy Materials Context:\n{rag_context}\n\nUser Question: {user_input}"
        else:
            system_instruction = "You are an AI Study Buddy. Provide factual and concise answers based on your general knowledge. Respond politely."
            prompt_text = f"{system_instruction}\n\nUser Question: {user_input}"
            
    # Add the user's new message to the history for the AI
    current_conversation_history.append({"role": "user", "parts": [{"text": prompt_text}]})
    
    body = {"contents": current_conversation_history}

    ai_message = ""
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, json=body)
        response.raise_for_status()
        result = response.json()
        
        if 'candidates' not in result or not result['candidates']:
            raise KeyError("No candidates found in response")

        ai_message_parts = result['candidates'][0]['content']['parts']
        ai_message = "".join(part['text'] for part in ai_message_parts if 'text' in part)

        # Add the model's response to the in-memory history for the next turn
        current_conversation_history.append({"role": "model", "parts": [{"text": ai_message}]})

        # Save to persistent storage
        new_message = Message(user_input=user_input, ai_response=ai_message, session_id=session_id)
        db.session.add(new_message)
        db.session.commit()

        return jsonify({"response": ai_message})

    except requests.exceptions.RequestException as e:
        print(f"Error calling Gemini API: {e}")
        # Fallback for API errors
        fallback_message = "Sorry, I'm having trouble communicating with the AI service right now. Please try again later."
        # Store a simplified error message
        new_message = Message(user_input=user_input, ai_response=fallback_message, session_id=session_id)
        db.session.add(new_message)
        db.session.commit()
        return jsonify({"response": fallback_message}), 500
    except KeyError as e:
        print(f"Error parsing Gemini API response: {e}")
        # Fallback for parsing errors
        fallback_message = "Sorry, I received an unexpected response from the AI. This might be a temporary issue."
        new_message = Message(user_input=user_input, ai_response=fallback_message, session_id=session_id)
        db.session.add(new_message)
        db.session.commit()
        return jsonify({"response": fallback_message}), 500
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        # General fallback
        fallback_message = "An unexpected error occurred. Please try again."
        new_message = Message(user_input=user_input, ai_response=fallback_message, session_id=session_id)
        db.session.add(new_message)
        db.session.commit()
        return jsonify({"response": fallback_message}), 500


# --- Speech-to-Text Endpoint (Google Speech Recognition Library) ---
# --- Speech-to-Text Endpoint (Google Speech Recognition Library) ---
@app.route("/speech_to_text", methods=["POST"])
def speech_to_text():
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files['audio']
    recognizer = sr.Recognizer()

    try:
        # Determine the format of the incoming audio.
        # MediaRecorder typically outputs 'webm' by default in many browsers.
        # If your browser produces a different format, you might need to adjust 'format="webm"'
        # in the from_file call or ensure your JS explicitly sets a different type.
        
        # Read the audio file into an AudioSegment
        audio_data_pydub = AudioSegment.from_file(audio_file, format="webm")
        
        # Export to WAV format in memory for speech_recognition
        wav_buffer = io.BytesIO()
        audio_data_pydub.export(wav_buffer, format="wav")
        wav_buffer.seek(0) # Rewind the buffer to the beginning

        with sr.AudioFile(wav_buffer) as source:
            audio = recognizer.record(source) # Read the entire audio file
            text = recognizer.recognize_google(audio) # Using Google Web Speech API
            return jsonify({"text": text})
    except sr.UnknownValueError:
        print("Google Speech Recognition could not understand audio")
        return jsonify({"error": "Could not understand audio"}), 400
    except sr.RequestError as e:
        # This error typically means there's an issue with reaching the Google API
        # (e.g., no internet connection, API limits, etc.)
        print(f"Could not request results from Google Speech Recognition service; {e}")
        return jsonify({"error": f"Could not request results from speech recognition service; {e}"}), 500
    except Exception as e:
        # Catch all other exceptions for more specific debugging
        print(f"An unexpected error occurred in speech_to_text processing: {e}")
        return jsonify({"error": f"An unexpected error occurred during speech processing: {str(e)}"}), 500

# --- Text-to-Speech Endpoint (gTTS) ---
@app.route("/text_to_speech", methods=["POST"])
def text_to_speech():
    data = request.json
    text = data.get("text")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        tts = gTTS(text=text, lang='en')
        audio_buffer = io.BytesIO()
        tts.write_to_fp(audio_buffer)
        audio_buffer.seek(0)
        return audio_buffer.getvalue(), 200, {'Content-Type': 'audio/mpeg'}
    except Exception as e:
        print(f"Error in text_to_speech: {e}")
        return jsonify({"error": "Failed to convert text to speech."}), 500


if __name__ == "__main__":
    # Create the data directory if it doesn't exist
    os.makedirs('data', exist_ok=True)
    # Create a dummy study_materials.txt if it doesn't exist for demo purposes
    if not os.path.exists("data/study_materials.txt"):
        with open("data/study_materials.txt", "w", encoding="utf-8") as f:
            f.write("Mental health is crucial for overall well-being.\n")
            f.write("The capital of France is Paris.\n")
            f.write("Psychology is the scientific study of mind and behavior.\n")
            f.write("Cognitive Behavioral Therapy (CBT) is a common therapeutic approach.\n")
            f.write("Machine learning is a subset of AI.\n")
            f.write("A balanced diet and regular exercise contribute to good mental health.\n")
            f.write("Neural networks are fundamental to deep learning.\n")
    app.run(debug=True)