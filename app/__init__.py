from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mqtt import Mqtt
from flask_socketio import SocketIO
from flask_bootstrap import Bootstrap

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite+pysqlite:///battery.db"
app.config['SECRET_KEY'] = ''
app.config['MQTT_BROKER_URL'] = 'io.adafruit.com'
app.config['MQTT_BROKER_PORT'] = 1883
app.config['MQTT_USERNAME'] = 'Hor'
app.config['MQTT_PASSWORD'] = ''
app.config['MQTT_KEEPALIVE'] = 5
app.config['MQTT_TLS_ENABLED'] = False
app.config['MQTT_CLEAN_SESSION'] = False
db = SQLAlchemy()
db.init_app(app)
mqtt = Mqtt(app)
socketio = SocketIO(app)
bootstrap = Bootstrap(app)
login_manager = LoginManager()
login_manager.init_app(app)