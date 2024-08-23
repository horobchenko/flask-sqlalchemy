from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mqtt import Mqtt
from flask_socketio import SocketIO
from flask_bootstrap import Bootstrap

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite+pysqlite:///battery.db"
app.config['SECRET_KEY'] = 'jguitc6747990h'
app.config['MQTT_BROKER_URL'] = 'io.adafruit.com' # use the free broker from HIVEMQ
app.config['MQTT_BROKER_PORT'] = 1883  # default port for non-tls connection
app.config['MQTT_USERNAME'] = 'Hor'  # set the username here if you need authentication for the broker
app.config['MQTT_PASSWORD'] = "aio_rWhm93j8NmzYixdrDGNk9Cr98ua0" # set the password here if the broker demands authentication
#app.config['MQTT_KEEPALIVE'] = 120  # set the time interval for sending a ping to the broker to 5 seconds
app.config['MQTT_TLS_ENABLED'] = False  # set TLS to disabled for testing purposes
db = SQLAlchemy()
db.init_app(app)
mqtt = Mqtt(app)

socketio = SocketIO(app)
bootstrap = Bootstrap(app)
login_manager = LoginManager()
login_manager.init_app(app)