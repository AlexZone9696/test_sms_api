from flask import Flask, render_template, request, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
import requests, time, json, os

app = Flask(__name__)
app.secret_key = 'секретный_ключ'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tmp/database.db'
db = SQLAlchemy(app)

API_KEY = 'ВАШ_API_КЛЮЧ_ОТ_SMSHUB'

if not os.path.exists('tmp'):
    os.makedirs('tmp')
if not os.path.exists('tmp/database.db'):
    with app.app_context():
        db.create_all()

with open('ton_config.json') as f:
    TON_CONFIG = json.load(f)
TON_WALLET = TON_CONFIG['wallet']

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(50), unique=True)
    username = db.Column(db.String(100))
    balance = db.Column(db.Float, default=0)
    is_admin = db.Column(db.Boolean, default=False)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    service = db.Column(db.String(20))
    number = db.Column(db.String(20))
    sms_code = db.Column(db.String(20))
    status = db.Column(db.String(20))
    date = db.Column(db.String(20))

@app.route('/')
def index():
    return render_template('index.html', ton_address=TON_WALLET)

@app.route('/admin')
def admin():
    user = User.query.get(session.get('user_id'))
    if user and user.is_admin:
        users = User.query.all()
        orders = Order.query.all()
        return render_template('admin.html', users=users, orders=orders)
    return 'Доступ запрещён', 403

@app.route('/auth', methods=['POST'])
def auth():
    tg_id = request.form['id']
    username = request.form['username']
    user = User.query.filter_by(telegram_id=tg_id).first()
    if not user:
        user = User(telegram_id=tg_id, username=username, balance=0.5)
        db.session.add(user)
        db.session.commit()
    session['user_id'] = user.id
    return jsonify({'status': 'ok', 'balance': user.balance, 'is_admin': user.is_admin})

@app.route('/get_number', methods=['POST'])
def get_number():
    if 'user_id' not in session:
        return jsonify({'error': 'not_authenticated'})
    service = request.form['service']
    country = request.form['country']
    r = requests.get('https://smshub.org/stubs/handler_api.php', params={
        'api_key': API_KEY, 'action': 'getNumber', 'service': service, 'country': country
    }).text
    if r.startswith('ACCESS_NUMBER'):
        _, id_request, number = r.split(':')
        order = Order(user_id=session['user_id'], service=service, number=number, sms_code='', status='WAIT', date=time.strftime('%Y-%m-%d %H:%M:%S'))
        db.session.add(order)
        db.session.commit()
        return jsonify({'id': id_request, 'number': number})
    else:
        return jsonify({'error': r})

@app.route('/get_sms', methods=['POST'])
def get_sms():
    id_request = request.form['id']
    for _ in range(10):
        r = requests.get('https://smshub.org/stubs/handler_api.php', params={
            'api_key': API_KEY, 'action': 'getStatus', 'id': id_request
        }).text
        if r.startswith('STATUS_OK'):
            code = r.split(':')[1]
            order = Order.query.filter_by(user_id=session['user_id']).order_by(Order.id.desc()).first()
            order.sms_code = code
            order.status = 'RECEIVED'
            db.session.commit()
            return jsonify({'code': code})
        elif r == 'STATUS_WAIT_CODE':
            time.sleep(2)
        else:
            return jsonify({'error': r})
    return jsonify({'error': 'Timeout'})

@app.route('/orders')
def orders():
    orders = Order.query.filter_by(user_id=session.get('user_id')).order_by(Order.id.desc()).all()
    return jsonify([{
        'service': o.service, 'number': o.number, 'status': o.status,
        'code': o.sms_code, 'date': o.date
    } for o in orders])

@app.route('/add_balance', methods=['POST'])
def add_balance():
    user = User.query.get(session['user_id'])
    amount = float(request.form['amount'])
    user.balance += amount
    db.session.commit()
    return jsonify({'new_balance': user.balance})
