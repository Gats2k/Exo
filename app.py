from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def chat():
    mock_history = [
        {
            'title': 'Équations du second degré',
            'subject': 'Mathématiques',
            'time': '2h ago'
        },
        {
            'title': 'Lois de Newton',
            'subject': 'Physique', 
            'time': '1j ago'
        },
        {
            'title': 'Méthode de travail',
            'subject': 'Général',
            'time': '2j ago'
        }
    ]
    
    return render_template('chat.html', history=mock_history, credits=42)
