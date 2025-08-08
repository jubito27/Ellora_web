from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from flask_cors import CORS
from PIL import Image
import google.generativeai as genai
import os
import base64
import io
import speech_recognition as sr
import time
from gtts import gTTS
import tempfile
from io import BytesIO
from werkzeug.utils import secure_filename
from datetime import datetime
import uuid
import json
import firebase_admin
from firebase_admin import credentials, auth, db
from functools import wraps
from authlib.integrations.flask_client import OAuth
from google.auth.transport.requests import Request
from google.oauth2 import service_account
import logging

app = Flask(__name__)
CORS(app)

# Configuration
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'super-ellora-secret')  # FIXED: Do NOT use your Google API Key!
app.config['SESSION_COOKIE_NAME'] = 'ellora_session'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Set up logging
logging.basicConfig(level=logging.INFO)

# Initialize Firebase Admin SDK
try:
    # Get the service account JSON from environment variable
    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

    if not service_account_json:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON environment variable not set")
        print("Firebase not Initialized")

    # Parse JSON string into Python dict
    service_account_dict = json.loads(service_account_json)

    # Create credentials from dict
    cred = credentials.Certificate(service_account_dict)

    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://ellora-ai-default-rtdb.firebaseio.com/'
    })
    print("Firebase initialized successfully")

except Exception as e:
    print(f"Firebase initialization error: {e}")
# Configure Gemini/Google Generative AI
try:
    genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
    model = genai.GenerativeModel(model_name="gemini-2.0-flash")
except Exception as e:
    app.logger.exception("Google Generative AI configuration error")

try:
    # --- OAuth Setup ---
    oauth = OAuth(app)
    google = oauth.register(
        name='google',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )
    facebook = oauth.register(
        name='facebook',
        client_id=os.getenv('FACEBOOK_CLIENT_ID'),  # FIXED: removed trailing space
        client_secret=os.getenv('FACEBOOK_CLIENT_SECRET'),
        access_token_url='https://graph.facebook.com/v17.0/oauth/access_token',
        access_token_params=None,
        authorize_url='https://www.facebook.com/v17.0/dialog/oauth',
        authorize_params=None,
        api_base_url='https://graph.facebook.com/v17.0/',
        client_kwargs={'scope': 'email'}
    )
except Exception as e:
    app.logger.exception("OAuth registration error")

avatars = {
    "Sarcastic 🥱": "🥱",
    "Friendly 😊": "😊",
    "Professional 🧑💼": "🧑💼",
    "Love Poet 🥰": "🥰",
    "Vedic Vyasa 🕉️": "🕉️",
    "Medic Expert ⚕️": "⚕️"
}

def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required', 'redirect': '/login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_instruction(role):
    instructions = {
        "Sarcastic 🥱": (
            "You are Ellora AI, a dark-humored, sarcastic, and witty assistant created by Abhishek Sharma. "
            "Use short, punchy replies with simple words. Always serve with clever insights and dark humor when appropriate. "
            "Format your responses with proper markdown including headers, code blocks, and structured content."
        ),
        "Friendly 😊": (
            "You are Ellora AI, a friendly and kind assistant created by Abhishek Sharma. "
            "Always provide clear, helpful, supportive answers in a positive and energetic tone. "
            "Format your responses with proper markdown including headers, bullet points, and structured explanations."
        ),
        "Professional 🧑💼": (
            "You are Ellora AI, a highly professional AI assistant created by Abhishek Sharma. "
            "Maintain formal tone and accurate responses. Use structured formatting with clear sections, "
            "bullet points, and professional language."
        ),
        "Love Poet 🥰": (
            "You are Ellora AI, a romantic poet created by Abhishek Sharma. "
            "Use poetic language, metaphors, and vivid imagery. Format responses with beautiful structure, "
            "verses, and romantic expressions in markdown format."
        ),
        "Vedic Vyasa 🕉️": (
            "You are the great sage Vyasa, master of Vedas, created as Ellora AI by Abhishek Sharma. "
            "Answer from sacred texts using deep spiritual knowledge. Use proper markdown formatting "
            "with sections for different aspects of wisdom."
        ),
        "Medic Expert ⚕️": (
            "You are Ellora AI, a medical expert created by Abhishek Sharma. "
            "Provide accurate, professional medical information with proper disclaimers. "
            "Use structured markdown with clear sections, symptoms, treatments, and recommendations."
        )
    }
    return instructions.get(role, "You are Ellora AI, a helpful assistant created by Abhishek Sharma.")

def get_access_token():
    service_account_file = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not service_account_file or not os.path.exists(service_account_file):
        raise ValueError("Service account file not found or environment variable not set")

    credentials_obj = service_account.Credentials.from_service_account_file(
        service_account_file,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    credentials_obj.refresh(Request())
    return credentials_obj.token

def save_message_to_firebase(user_id, conversation_id, role, content, ai_response):
    try:
        ref = db.reference(f'chats/{user_id}/{conversation_id}/messages')
        ref.push({
            'user_message': content,
            'ai_response': ai_response,
            'role': role,
            'timestamp': datetime.now().isoformat()
        })
        # Update conversation metadata
        conv_ref = db.reference(f'chats/{user_id}/{conversation_id}')
        conv_data = conv_ref.get()
        if not conv_data:
            conv_ref.set({
                'title': content[:50] + '...' if len(content) > 50 else content,
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'role': role
            })
        else:
            conv_ref.update({'last_updated': datetime.now().isoformat()})
    except Exception as e:
        app.logger.error(f"Error saving to Firebase: {e}")

def get_user_conversations(user_id):
    try:
        ref = db.reference(f'chats/{user_id}')
        conversations = ref.get()
        return conversations or {}
    except Exception as e:
        app.logger.error(f"Error getting conversations: {e}")
        return {}

def generate_response(user_input, role, user_id, conversation_id, uploaded_image=None, uploaded_file=None):
    instruction = get_instruction(role)
    enhanced_instruction = f"""
    {instruction}
    IMPORTANT FORMATTING GUIDELINES:
    1. Always structure your responses with clear markdown headers (##, ###)
    2. Use code blocks with proper language specification for any code
    3. Include bullet points and numbered lists for better readability
    4. Use **bold** for emphasis and *italic* for subtle emphasis
    5. Provide comprehensive answers with proper explanations
    6. If discussing problems, always explain the issue first, then provide solutions
    """
    # Get conversation history from Firebase
    try:
        ref = db.reference(f'chats/{user_id}/{conversation_id}/messages')
        messages = ref.get()
        history_text = ""
        if messages:
            for msg_id, msg_data in messages.items():
                history_text += f"User: {msg_data.get('user_message', '')}\nEllora: {msg_data.get('ai_response', '')}\n"
    except Exception:
        history_text = ""

    full_prompt = f"{enhanced_instruction}\n\n{history_text}\n\nUser: {user_input}"

    try:
        if uploaded_image:
            response = model.generate_content([full_prompt, uploaded_image], stream=False)
        elif uploaded_file:
            full_prompt += f"\n\nAttached file content:\n{uploaded_file}"
            response = model.generate_content(full_prompt)
        else:
            response = model.generate_content(full_prompt)
        # Save to Firebase
        save_message_to_firebase(user_id, conversation_id, role, user_input, response.text)
        return {"response": response.text, "sources": []}
    except Exception as e:
        return {"response": f"⚠️ **Error**: {str(e)}", "sources": []}

chat_sessions = {}  # For guests

def guest_response(user_input, role, session_id, uploaded_image=None, uploaded_file=None):
    instruction = get_instruction(role)
    enhanced_instruction = f"""
    {instruction}
    IMPORTANT FORMATTING GUIDELINES:
    1. Always structure your responses with clear markdown headers (##, ###)
    2. Use code blocks with proper language specification for any code
    3. Include bullet points and numbered lists for better readability
    4. Use **bold** for emphasis and *italic* for subtle emphasis
    5. Provide comprehensive answers with proper explanations
    6. If discussing problems, always explain the issue first, then provide solutions
    """
    chat_history = chat_sessions.get(session_id, [])
    history_text = "\n".join([f"User: {m['user']}\nEllora: {m['assistant']}" for m in chat_history])
    full_prompt = f"{enhanced_instruction}\n\n{history_text}\n\nUser: {user_input}"

    try:
        if uploaded_image:
            response = model.generate_content([full_prompt, uploaded_image], stream=False)
        elif uploaded_file:
            full_prompt += f"\n\nAttached file content:\n{uploaded_file}"
            response = model.generate_content(full_prompt)
        else:
            response = model.generate_content(full_prompt)
        return {"response": response.text, "sources": []}
    except Exception as e:
        return {"response": f"⚠️ **Error**: {str(e)}", "sources": []}

def get_first_avatar_char(name, email):
    if name: return name[0].upper()
    if email: return email[0].upper()
    return "A"

@app.route('/')
def index():
    if session.get('user_id'):
        return render_template('index.html',
            user_email=session.get('user_email'),
            user_name=session.get('user_name'),
            profile_photo=session.get('profile_photo'),
            provider=session.get('provider', 'basic')
        )
    return render_template('guest.html')

@app.route('/auth')
def auth_page():
    return render_template('auth.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

# --- Registration Endpoint ---
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        name = data.get('name', '')
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400

        # Create user in Firebase Auth
        user = auth.create_user(
            email=email,
            password=password,
            display_name=name
        )
        # Save user profile
        user_ref = db.reference(f'users/{user.uid}')
        user_ref.set({
            'email': email,
            'name': name,
            'created_at': datetime.now().isoformat()
        })

        session['user_id'] = user.uid
        session['user_email'] = email
        session['user_name'] = name
        return jsonify({'success': True, 'message': 'Registration successful'})
    except Exception as e:
        app.logger.error(f"Registration error: {e}")
        return jsonify({'error': str(e)}), 400

# --- SECURE Login via Firebase ID Token issued by client ---
@app.route('/api/login', methods=['POST'])
def login():
    """
    The frontend (web/mobile app) should use the Firebase JS SDK to sign the user in,
    then POST the raw ID token to this backend for session authentication/verification.
    """
    try:
        data = request.get_json()
        id_token = data.get('idToken')
        if not id_token:
            return jsonify({'error': 'No ID token provided'}), 400

        # Firebase ID token verification (raises error if invalid or expired)
        decoded_token = auth.verify_id_token(id_token)
        user_id = decoded_token['uid']
        user_info = auth.get_user(user_id)
        session['user_id'] = user_id
        session['user_email'] = user_info.email
        session['user_name'] = user_info.display_name
        return jsonify({'success': True, 'message': 'Login successful'})
    except Exception as e:
        app.logger.error(f"Login error: {e}")
        return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logout successful'})

@app.route('/logout')
def logout_get():
    session.clear()
    return redirect('/')

# --- Google Auth ---
@app.route('/auth/google')
def google_login():
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def google_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            return "No userinfo returned from Google.", 400

        email = user_info.get('email')
        name = user_info.get('name', 'User')
        photo = user_info.get('picture')

        if not email:
            return "Google account did not provide an email address.", 400

        try:
            user = auth.get_user_by_email(email)
        except firebase_admin._auth_utils.UserNotFoundError:
            # If user doesn't exist, create one.
            user = auth.create_user(email=email, display_name=name)
        session['user_id'] = user.uid
        session['user_email'] = email
        session['user_name'] = name
        session['profile_photo'] = photo
        session['provider'] = 'google'
        return redirect('/')
    except Exception as e:
        app.logger.error(f"Google login callback error: {e}")
        return "An error occurred during Google login.", 500


# --- Facebook Auth ---
@app.route('/auth/facebook')
def facebook_login():
    redirect_uri = url_for('facebook_callback', _external=True)
    return facebook.authorize_redirect(redirect_uri)

@app.route('/auth/facebook/callback')
def facebook_callback():
    token = facebook.authorize_access_token()
    user_info = facebook.get('me?fields=id,name,email,picture.type(large)').json()
    email = user_info.get('email')
    name = user_info['name']
    photo = user_info['picture']['data']['url']
    try:
        user = auth.get_user_by_email(email)
    except Exception:
        user = auth.create_user(email=email, display_name=name)
    session['user_id'] = user.uid
    session['user_email'] = email
    session['user_name'] = name
    session['profile_photo'] = photo
    session['provider'] = 'facebook'
    return redirect('/')

@app.route('/api/chat', methods=['POST'])
def chat():
    # Authenticated user
    if session.get('user_id'):
        user_id = session['user_id']
        try:
            data = request.get_json()
            message = data.get('message', '')
            role = data.get('role', 'Friendly 😊')
            conversation_id = data.get('conversation_id') or str(uuid.uuid4())
            if not message:
                return jsonify({'error': 'No message provided'}), 400
            result = generate_response(message, role, user_id, conversation_id)
            result['conversation_id'] = conversation_id
            return jsonify(result)
        except Exception as e:
            app.logger.error(f"Authenticated chat error: {e}")
            return jsonify({'error': str(e)}), 500
    else:  # Guest user
        try:
            data = request.get_json()
            message = data.get('message', '')
            role = data.get('role', 'Friendly 😊')
            session_id = data.get('session_id', 'default')
            if not message:
                return jsonify({'error': 'No message provided'}), 400
            result = guest_response(message, role, session_id)
            if session_id not in chat_sessions:
                chat_sessions[session_id] = []
            chat_sessions[session_id].append({
                'user': message,
                'assistant': result['response'],
                'timestamp': datetime.now().isoformat()
            })
            if len(chat_sessions[session_id]) > 10:
                chat_sessions[session_id] = chat_sessions[session_id][-10:]
            return jsonify(result)
        except Exception as e:
            app.logger.error(f"Guest chat error: {e}")
            return jsonify({'error': str(e)}), 500

@app.route('/api/conversations', methods=['GET'])
@require_auth
def get_conversations():
    try:
        user_id = session['user_id']
        conversations = get_user_conversations(user_id)
        return jsonify(conversations)
    except Exception as e:
        app.logger.error(f"Get conversations error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/new-chat', methods=['POST'])
@require_auth
def new_chat():
    try:
        conversation_id = str(uuid.uuid4())
        return jsonify({'conversation_id': conversation_id})
    except Exception as e:
        app.logger.error(f"New chat error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete-conversation', methods=['POST'])
@require_auth
def delete_conversation():
    try:
        data = request.get_json()
        conversation_id = data.get('conversation_id')
        user_id = session['user_id']
        if not conversation_id:
            return jsonify({'error': 'Conversation ID required'}), 400
        # Delete from Firebase
        ref = db.reference(f'chats/{user_id}/{conversation_id}')
        ref.delete()
        return jsonify({'success': True, 'message': 'Conversation deleted'})
    except Exception as e:
        app.logger.error(f"Delete conversation error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/text-to-speech', methods=['POST'])
@require_auth
def text_to_speech():
    try:
        data = request.get_json()
        text = data.get('text', '')
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        tts = gTTS(text=text, lang='en', tld='com', slow=False)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
            tts.save(tmp_file.name)
        with open(tmp_file.name, 'rb') as audio_file:
            audio_data = audio_file.read()
        os.unlink(tmp_file.name)
        audio_b64 = base64.b64encode(audio_data).decode()
        return jsonify({'audio': audio_b64})
    except Exception as e:
        app.logger.error(f"Text-to-speech error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)








