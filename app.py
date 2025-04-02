from flask import Flask, request, jsonify
from flask_cors import CORS
from huggingface_hub import InferenceClient
import os
import traceback
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import time
app = Flask(__name__, static_folder='static')
CORS(app)  # Enable CORS for all routes

# Initialize client with error handling
try:
    print("⏳ Loading model...")
    #model_name = "microsoft/phi-1_5"
    model_name = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="auto",
    torch_dtype=torch.float16
)
    print("✅ Model loaded successfully")

except Exception as e:
    print(f"❌ Model loading failed: {str(e)}")
    print(f"Initialization error: {str(e)}")
    model = None

SYSTEM_PROMPT = """You are Ellora AI, created by Abhishek Sharma. Follow these rules:
1. When asked your name, respond: "My name is Ellora AI"
2. When asked about creator, respond: "I was created by Abhishek Sharma"
3. Never describe yourself as just an AI model"""

@app.route('/')
def home():
    return app.send_static_file('index.html')
@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"})

def generate_response(user_input):
    try:
        if not isinstance(user_input, str) or len(user_input.strip()) == 0:
            raise ValueError("Empty input")
        prompt = f"""<|system|>{SYSTEM_PROMPT}</s><|user|>{user_input}</s><|assistant|>"""
        
        inputs = tokenizer(prompt, return_tensors="pt").to("cpu")
        if inputs["input_ids"].shape[1] > 1024:  # Prevent overly long prompts
            raise ValueError("Input too long")
        outputs = model.generate(
            input_ids = inputs["input_ids"],
            attention_mask = inputs["attention_mask"],
            max_new_tokens=200,
            temperature=0.7,
            do_sample = True,
            pad_token_id = tokenizer.eos_token_id
            # num_return_sequence = 1,
            # truncation = True
        )
        return tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    except Exception as e:
        print(f"Generation error : {str(e)}")
        raise
@app.before_request
def handle_timeout():
    time.sleep(0.1)

@app.route('/chat', methods=['POST'])
def chat():
    start_time = time.time()
    try:
        print("\n=== Incoming Request ===")
        print(f"Headers: {request.headers}")
        print(f"Data: {request.get_json()}")
        
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data received"}), 400
        user_message = data.get('message', '').lower()
        print(f"Processing message: {user_message}")
        # Handle identity questions directly
        if "your name" in user_message:
            return jsonify({"response": "My name is Ellora AI"})
        if "who created you" in user_message or "who made you" in user_message:
            return jsonify({"response": "I was created by Abhishek Sharma"})
        
        if not model:
            return jsonify({"error": "Model not loaded"}) , 503
        print("Calling model...")
        # response = client.chat_completion(
        #     messages=[
        #         {"role": "system", "content": SYSTEM_PROMPT},
        #         {"role": "user", "content": user_message}
        #     ],
        #     max_tokens=200,
        #     temperature=0.7
        # )

        while time.time() - start_time < 290:
            full_response = generate_response(user_message)
            print("Model response received")
            #return jsonify({"response": response.choices[0].message.content})
            response = full_response.split("<|assistant|>")[-1].strip()
            print(f"🤖 Response: {response[:50]}...") 
            return jsonify({"response": response})
        return jsonify({"error": "Processing timeout"}), 504
    except Exception as e:
        print("\n⚠️ Error Traceback ⚠️")
        traceback.print_exc()
        return jsonify({"response": "I'm having trouble processing your request"}), 500

# if __name__ == '__main__':
#     port = int(os.environ.get('PORT', 5001))
#     app.run(host='0.0.0.0', port=port , debug=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"\n🚀 Starting server on port {port}")
    print(f"🔌 Model: {model_name}")
    print(f"💻 Device: {'GPU' if torch.cuda.is_available() else 'CPU'}")
    app.run(host='0.0.0.0', port=port)



# from flask import Flask, request, jsonify
# from flask_cors import CORS
# from transformers import pipeline  # Using pipeline for better performance
# import torch
# import time

# app = Flask(__name__, static_folder='static')
# CORS(app)

# # Configuration
# MODEL_NAME = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"  # Good balance of speed/quality
# MAX_TOKENS = 150  # Reduced from 200 for faster responses
# DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# # Initialize model
# try:
#     print("⏳ Loading model (this may take a few minutes)...")
#     pipe = pipeline(
#         "text-generation",
#         model=MODEL_NAME,
#         device=DEVICE,
#         torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32
#     )
#     print(f"✅ Model loaded on {DEVICE.upper()}")
# except Exception as e:
#     print(f"❌ Model loading failed: {str(e)}")
#     pipe = None

# SYSTEM_PROMPT = """<<SYS>>
# You are Ellora AI. Respond with:
# 1. "My name is Ellora AI" when asked your name
# 2. "I was created by Abhishek Sharma" when asked about creator
# Keep responses under 3 sentences.
# <</SYS>>"""

# @app.route('/chat', methods=['POST'])
# def chat():
#     start_time = time.time()
    
#     try:
#         # Validate request
#         data = request.get_json()
#         if not data or 'message' not in data:
#             return jsonify({"error": "Invalid request format"}), 400
            
#         user_message = data['message'].lower()
        
#         # Predefined responses
#         if "your name" in user_message:
#             return jsonify({"response": "My name is Ellora AI"})
#         if "who created you" in user_message:
#             return jsonify({"response": "I was created by Abhishek Sharma"})
        
#         if not pipe:
#             return jsonify({"error": "Model not available"}), 503
        
#         # Generate response with performance optimizations
#         prompt = f"{SYSTEM_PROMPT}\nUser: {user_message}\nAssistant:"
        
#         response = pipe(
#             prompt,
#             max_new_tokens=MAX_TOKENS,
#             temperature=0.7,
#             do_sample=True,
#             num_return_sequences=1,
#             truncation=True
#         )[0]['generated_text']
        
#         # Extract only the assistant's response
#         assistant_response = response.split("Assistant:")[-1].strip()
        
#         print(f"⏱️ Response generated in {time.time()-start_time:.2f}s")
#         return jsonify({"response": assistant_response})
        
#     except Exception as e:
#         print(f"⚠️ Error: {str(e)}")
#         return jsonify({"error": "Processing error"}), 500

# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=5001, threaded=True)