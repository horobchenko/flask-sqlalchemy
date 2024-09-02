import dataclasses
import string
from datetime import datetime
from typing import List
import lmfit
import numpy as np
import scipy
import pandas as pd
from scipy.signal import find_peaks, peak_prominences, peak_widths
from sqlalchemy.orm import declared_attr, mapped_column, Mapped,composite
from app import app, db, login_manager, mqtt, socketio,bootstrap
import logging
from flask_login import UserMixin

class TableNameMixin:
    ''' Міксин, що встановлює назву таблиці відповідно назві класу в нижньому регістрі'''
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower()
class User(db.Model, TableNameMixin, UserMixin):
    '''Клас користувача додатку'''

    id = mapped_column(db.Integer, primary_key=True)
    name = mapped_column(db.String(50), unique=True)
    password = mapped_column(db.Integer)
    battery: Mapped["Battery"] = db.relationship(back_populates="user", cascade="all, delete-orphan")

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, name={self.name!r}, battery={self.battery!r})"
@dataclasses.dataclass
class Parameters:
    '''Клас для параметрів батареї, що використовуються в розрахунках'''

    first_icacycle: int
    last_icacycle: int
    first_ccctcycle: int
    last_ccctcycle: int
    ccct_cycles_stap: int
    filter_parameter: int
    peak: int
    lmfit_model: str
class Battery(db.Model,  TableNameMixin):
    '''Клас акумулятора користувача'''

    id = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    bat_type:Mapped[str]= mapped_column(db.String(1))
    nominal_charge: Mapped[float] = mapped_column(nullable=True, default=1.0)
    parameters: Mapped[Parameters] = composite(mapped_column("f_ica_c", nullable=True), mapped_column("l_ica_c", nullable=True),mapped_column("f_ccct_c", nullable=True),
                                               mapped_column("l_ccct_c", nullable=True), mapped_column("ccct_stap", nullable=True), mapped_column("filter", nullable=True),
                                               mapped_column("peak", nullable=True), mapped_column("model", nullable=True))
    user_id = mapped_column(db.Integer, db.ForeignKey("user.id"))
    user: Mapped["User"] = db.relationship(back_populates="battery")
    ccct_data: Mapped[List["CcctData"]] = db.relationship(back_populates="battery", cascade="all, delete-orphan")
    ica_data: Mapped[List["IcaData"]] = db.relationship(back_populates="battery", cascade="all, delete-orphan")
    left_border = mapped_column(db.Integer, nullable=True)
    right_border = mapped_column(db.Integer, nullable=True)
    stop_time = mapped_column(db.Integer, nullable=True)

    def __repr__(self) -> str:
        return f"Battery(id={self.id!r}, type = {self.bat_type!r}, ccct_data ={self.ccct_data!r}, ica_data = {self.ica_data!r}, , nominal charge = {self.nominal_charge!r})"

class CcctData(db.Model, TableNameMixin):
    '''Клас для даних зарядного часу в межах попередньо розрахованого інтервалу напруги'''

    id: Mapped[int] = mapped_column(primary_key=True)
    overal_charge: Mapped[float] = mapped_column(nullable=True)
    nominal_charge = db.column_property(db.select(Battery.nominal_charge).scalar_subquery())
    timestamp: Mapped[datetime]
    ccct_time:Mapped[int]= mapped_column(nullable=True)
    soc = db.column_property(overal_charge / nominal_charge)
    battery: Mapped["Battery"] = db.relationship(back_populates="ccct_data")
    bat_id: Mapped[int] = mapped_column(db.ForeignKey("battery.id"))

    def __repr__(self) -> str:
        return f"Ccct(id={self.id!r}, soc={self.soc!r},  ccct = {self.ccct_time!r}, time = {self.timestamp!r} )"

class IcaData (db.Model, TableNameMixin):
    '''Клас для даних аналізу інкрементної кривої'''

    id: Mapped[int] = mapped_column(primary_key=True)
    stap_charge: Mapped[float] = mapped_column(nullable=True)
    stap_voltage: Mapped[float]= mapped_column(nullable=True)
    timestamp: Mapped[datetime] = mapped_column(nullable=True)
    bat_id: Mapped[int] = mapped_column(db.ForeignKey("battery.id"))
    battery:Mapped["Battery"] = db.relationship(back_populates="ica_data")

    def __repr__(self) -> str:
        return f"Ica(id={self.id!r}, charge={self.stap_charge!r},  voltage = {self.stap_voltage!r}, time = {self.timestamp!r})"

class BattaryAnalizer:
    '''Клас-інтерфейс методів аналізу даних акумулятору'''

    battery: Battery
    session: db.session

    def __init__(self, name: str, session: db.session) -> None:
        self.session = session
        stmt = db.select(db.Bundle("user", User.name), db.Bundle("battery", Battery.id),)\
                .join_from(User, Battery).where(User.name == name)
        for row in session.execute(stmt):
            battery_id = row.battery.id
            self.battery = self.session.get(Battery, battery_id)

    def gaussian_f(self, data: pd.DataFrame) -> pd.DataFrame:
        '''Ф-я для згладження інкрементної кривої накладанням фільтру Гаусса
        :return таблицю з данимим для побудови кривої після фільтрації'''

        s: int = self.battery.parameters.filter_parameter
        unfilt = data['dQ/dV']
        unfiltar = unfilt.values
        data['G_Smoothed_dQ/dV'] = scipy.ndimage.gaussian_filter(unfiltar, sigma=s)
        return data

    def detect_peak_width(self, data: pd.DataFrame) -> list:
        '''Ф-я для знаходження піків та їх ширини на графіку інкрементної кривої'''
        w = list()
        peaks, _ = find_peaks(data['G_Smoothed_dQ/dV'])
        prominences = peak_prominences(data['G_Smoothed_dQ/dV'], peaks)[0]
        for i in range(0, len(peaks)):
            rel_h = (data['G_Smoothed_dQ/dV'][peaks].iloc[i] - prominences[i]) / data['G_Smoothed_dQ/dV'][peaks].iloc[i]
            rel_h = 1 - rel_h
            width = peak_widths(data['G_Smoothed_dQ/dV'], np.array(peaks[i]).reshape(1), rel_height=rel_h)
            w.append(width)
        return w, peaks

    def make_inc_curve(self, staps) -> pd.DataFrame:
        '''Ф-я для побудови інкрементної кривої
        :return таблицю з даними для побудови інкрементної кривої'''
        stmt = db.select(Battery, db.func.count(IcaData.id)).join_from(Battery, IcaData).group_by(IcaData.bat_id)
        for bat, data_staps_count in self.session.execute(stmt):
                if bat.id == self.battery.id:
                    if data_staps_count == staps:
                        charge = self.session.scalars(db.select(IcaData.stap_charge).where(IcaData.bat_id == self.battery.id)).all()
                        voltage = self.session.scalars(db.select(IcaData.stap_voltage).where(IcaData.bat_id == self.battery.id)).all()
                        if staps == 30:
                            d = {'Voltage(V)': voltage, 'Charge': charge}
                            print("Got first ICA cycle data!")
                        else:
                            d = {'Voltage(V)': voltage[30:61], 'Charge': charge[30:61]}
                            print("Got second ICA cycle data!")
                        data = pd.DataFrame(data=d)
                        data['roundedV'] = round(data['Voltage(V)'], 3)
                        data = data.drop_duplicates(subset=['roundedV'])
                        data = data.reset_index(drop=True)
                        data['dV'] = data['Voltage(V)'].diff()
                        data['Charge_dQ'] = data['Charge'].diff()
                        data['dQ/dV'] = data['Charge_dQ'] / data['dV']
                        data[['dQ/dV', 'dV', 'Charge_dQ']] = data[['dQ/dV', 'dV', 'Charge_dQ']].fillna(0)
                        data = data[data['dQ/dV'] >= 0]
                        return data

    def estimate_stop_time(self):
            '''Ф-я для розрахунку зарядного часу, що відповідає початку старіння батареї'''
            stmt = db.select(Battery, db.func.count(CcctData.id)).join_from(Battery, CcctData).group_by(CcctData.bat_id)
            for bat, cycles_count in self.session.execute(stmt):
                if bat.id == self.battery.id:
                    if cycles_count == self.battery.parameters.last_ccctcycle:
                        ccct_time = self.session.scalars(db.select(CcctData.ccct_time).where(CcctData.bat_id == self.battery.id)).all()
                        soc = self.session.scalars(db.select(CcctData.soc).where(CcctData.bat_id == self.battery.id)).all()
                        df = pd.DataFrame(data = {'x': ccct_time, 'y':soc})
                        sort_df = df.sort_values(by=['x'])
                        y = sort_df['y'].to_xarray()
                        x = sort_df['x'].to_xarray()
                        model_name = self.battery.parameters.lmfit_model
                        if model_name=='linear_':
                            param = ['linear_intercept', 'linear_slope']
                            model_lmfit =lmfit.models.LinearModel(prefix='linear_')
                        elif model_name == 'quadratic_':
                            param = ['quadratic_a','quadratic_b','quadratic_c']
                            model_lmfit = lmfit.models.QuadraticModel(prefix='quadratic_')
                        else:
                            param = ['qubic_c0','qubic_c1','qubic_c2','qubic_c3']
                            model_lmfit = lmfit.models.PolynomialModel(degree=3, prefix='qubic_')
                        params = lmfit.Parameters()
                        for i in param:
                            params.add(i, value=0, min=-np.inf, max=np.inf)
                        result = model_lmfit.fit(y, params, x)
                        result.params.keys()
                        stop_time = 0.8 / (result.params.get(param[0]))
                        if model_name == 'linear_':
                            stop_time = stop_time
                        elif model_name == 'quadratic_':
                            stop_time = np.sqrt(stop_time)
                        else:
                            stop_time = np.cbrt(stop_time)
                        self.battery.stop_time =stop_time
                        print(f"Battery analisys is done!You will get a messege when your battery will stop it`s life!")
                        self.session.commit()


    def estimate_left_border(self) -> None:
        '''Ф-я для розрахунку лівої границі напруги, що відповідає старту
        для замірювання зарядного часу'''
        peak = self.battery.parameters.peak
        data = self.make_inc_curve(30)
        if data:
            data = self.gaussian_f(data)
            width, _ = self.detect_peak_width(data)
            w = np.array(width)
            index_left_v = data['Voltage(V)'][w[peak][2].round()].item()
            self.battery.left_border = index_left_v
            self.session.commit()
            print("Left voltage border set!")
            name = db.session.scalar(db.select(User.name).join(Battery, User.id == self.battery.user_id))
            mqtt.publish(f"{name}/l_border", index_left_v)
        else:
            print("Waiting for data to set voltage borders!")

    def estimate_right_border(self) -> None:
        '''Ф-ія для розрахунку правої границі напруги, що відповідає зупинці заміру зарядного часу'''
        peak = self.battery.parameters.peak
        data = self.make_inc_curve(60)
        if data:
            data = self.gaussian_f(data)
            width, peaks = self.detect_peak_width(data)
            w = np.array(width)
            peak_v = data['Voltage(V)'].iloc[peaks[peak]].item()
            self.battery.right_border = peak_v
            self.session.commit()
            print("Right voltage border set!")
            name = db.session.scalar(db.select(User.name).join(Battery, User.id == self.battery.user_id))
            mqtt.publish(f"{name}/r_border", peak_v)
        else:
            print("Waiting for data to set voltage borders!")


#####  Допоміжні функції  #########################
def insert_ica_data_by_name(name: str, value: float, field: string):
    '''Ф-ія додавання даних до БД за ім'ям користувача, отриманих від MQTT-брокера'''
    bat_id = bat_id_by_name(name)
    with app.app_context():
        stmt = db.select(Battery, IcaData.id).where(IcaData.stap_voltage!=0 and IcaData.stap_charge ==0).join_from(Battery, IcaData).group_by(IcaData.bat_id)
        data = db.session.execute(stmt).all()
        if data:
           for bat, ica_id in data:
            print(f"Дані без енергоємності: ID акумулятора - {bat.id}, ID даних - {ica_id}")
            if bat.id == bat_id and field == 'charge':
                    ica_data = IcaData.query.get(ica_id)
                    ica_data.stap_charge = value
                    print(f"ID акумулятора - {bat_id}. Дані енергоємності додані до даних напруги!")
                    db.session.commit()
            elif bat.id == bat_id and field == 'voltage':
                     print("Попередні дані енергоємності втрачені!")
                     db.session.execute(db.delete(IcaData).where(IcaData.id==ica_id))
                     db.session.commit()
                     print('Попередні дані напруги видалені через втрату даних енергоємності!')
            else:
               print(f"ID акумулятора {bat_id}. Нові дані")
               stmt = db.select(Battery, IcaData.id)\
                        .join_from(Battery, IcaData).group_by(IcaData.bat_id)\
                        .where(IcaData.stap_voltage == 0 and IcaData.stap_charge !=0)
               data = db.session.execute(stmt).all()
               if data:
                  for bat, ica_id in data:
                      if bat.id == bat_id:
                        print("Втрачені попередні дані напруги! ПОМИЛКА контроллера!")
                        ica_data = IcaData.query.get(ica_id)
                        db.session.delete(ica_data)
                        db.session.commit()
                        print('Попередні дані напруги видалені')
                        if field=='voltage':
                            db.session.execute(db.insert(IcaData).values(timestamp=db.func.now()).execution_options(render_nulls=True),
                            {"stap_charge": 0, "bat_id": bat_id, "stap_voltage": value})
                        print(f"ID акумулятора {bat_id}. Дані напруги додані!")
                        db.session.commit()
               else:
                   if field == 'voltage':
                       db.session.execute(db.insert(IcaData).values(timestamp=db.func.now()).execution_options(render_nulls=True),
                      {"stap_charge": 0, "bat_id": bat_id, "stap_voltage":value})
                       print(f"ID акумулятора {bat_id}.Дані напруги додані!")
                       db.session.commit()
        else:
            print(f"ID акумулятора {bat_id}.Нові дані")
            stmt = db.select(Battery, IcaData.id) \
                .join_from(Battery, IcaData).group_by(IcaData.bat_id) \
                .where(IcaData.stap_voltage == 0 and IcaData.stap_charge != 0)
            data = db.session.execute(stmt).all()
            if data:
                for bat, ica_id in data:
                    if bat.id == bat_id:
                        print("Втрачені попередні дані напруги! ПОМИЛКА контроллера!")
                        ica_data = IcaData.query.get(ica_id)
                        db.session.delete(ica_data)
                        print('Попередні дані напруги видалені')
                        if field == 'voltage':
                            db.session.execute(
                                db.insert(IcaData).values(timestamp=db.func.now()).execution_options(render_nulls=True),
                                {"stap_charge": 0, "bat_id": bat_id, "stap_voltage": value})
                        print(f"ID акумулятора {bat_id}.Дані напруги додані!")
                        db.session.commit()
            else:
                if field == "voltage":
                    db.session.execute(
                    db.insert(IcaData).values(timestamp=db.func.now()).execution_options(render_nulls=True),
                    {"stap_charge": 0, "bat_id": bat_id, "stap_voltage": value})
                    print(f"ID акумулятора {bat_id}.Дані напруги додані!")
                    db.session.commit()
        print(f"User {name} отримав ICA дані від брокера")

def insert_ccct_data_by_name(name: str, ccct_time: float, overal_charge: float):
    '''Ф-ія для додавання за ім'ям користувача до БД даних, отриманих від MQTT-брокера'''
    id = bat_id_by_name(name)
    with app.app_context():
        db.session.execute(db.insert(CcctData).values(timestamp=db.func.now()).execution_options(render_nulls=True),
            {"ccct_time": ccct_time, "overal_charge": overal_charge, "bat_id": id},
        )
        db.session.commit()
        print(f"User {name} resieved ccct data")
def bat_id_by_name(name: str):
    with app.app_context():
        stmt = db.select(db.Bundle("user", User.name), db.Bundle("battery", Battery.id), ).join_from(User, Battery).where(User.name == name)
        for row in db.session.execute(stmt):
            return row.battery.id

########  MQTT методи #######
logger = logging.getLogger(__name__)

@socketio.on('unsubscribe')
def handle_unsubscribe():
    mqtt.unsubscribe()
    print('Unsubscribe!')
@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
                data = dict(
                    topic=message.topic,
                    payload=message.payload.decode()
                )
                socketio.emit('mqtt_message', data=data)
                print(f'Дані {data.items()}')
                name = data.get("topic")
                name = name.rsplit('/')
                name = name[2]
                payload = data.get("payload")
                payload = payload.rsplit('"')
                for j in payload:
                    if j.startswith('ica-charge'):
                        for i in payload:
                            if (str.isdigit(i) or i.startswith('0.')):
                                float(i)
                                print(i)
                                insert_ica_data_by_name(name = name, value=i, field='charge')
                    elif j.startswith('ica-voltage'):
                        for i in payload:
                            if (str.isdigit(i) or i.startswith('0.') or i.startswith('1.') or i.startswith('2.') or i.startswith('3.') or i.startswith('4.')):
                                float(i)
                                print(i)
                                insert_ica_data_by_name(name = name, value=i, field='voltage')
                    elif j.startswith('ccct'):
                        for i in payload:
                            if (str.isdigit(i) or i.startswith('0.')):
                                float(i)
                                print(i)
                                insert_ccct_data_by_name(name = name, ccct_time=i, overal_charge=1)

@mqtt.on_log()
def handle_logging(client, userdata, level, buf):
    print(level, buf)








