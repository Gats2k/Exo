from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def chat():
    # Empty history list
    history = []
    return render_template('chat.html', history=history, credits=42)