import dataclasses
from datetime import datetime
from typing import List
import lmfit
import numpy as np
import scipy
import pandas as pd
from scipy.signal import find_peaks, peak_prominences, peak_widths
from sqlalchemy.orm import declared_attr, mapped_column, Mapped,composite
from app import db
from flask_login import UserMixin
from app import login_manager

class TableNameMixin:

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


class User(db.Model, TableNameMixin):

    id = mapped_column(db.Integer, primary_key=True)
    name = mapped_column(db.String(50), unique=True)
    password = mapped_column(db.Integer)
    battery: Mapped["Battery"] = db.relationship(back_populates="user")

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, name={self.name!r}, battery={self.battery!r})"


@dataclasses.dataclass
class Parameters:
    first_icacycle: int
    last_icacycle: int
    first_ccctcycle: int
    last_ccctcycle: int
    ccct_cycles_stap: int
    filter_parameter: int
    peak: int
    lmfit_model: str


class Battery(db.Model,  TableNameMixin):

    id = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    bat_type:Mapped[str]= mapped_column(db.String(1)) #Column("bat_type", String),comparator_factory=MyColumnComparator)
    nominal_charge: Mapped[float] = mapped_column(nullable=True)
    parameters: Mapped[Parameters] = composite(mapped_column("f_ica_c", nullable=True), mapped_column("l_ica_c", nullable=True),mapped_column("f_ccct_c", nullable=True),
                                               mapped_column("l_ccct_c", nullable=True), mapped_column("ccct_stap", nullable=True), mapped_column("filter", nullable=True),
                                               mapped_column("peak", nullable=True), mapped_column("model", nullable=True))

    user_id = mapped_column(db.Integer, db.ForeignKey("user.id"))
    user: Mapped["User"] = db.relationship(back_populates="battery")
    ccct_data: Mapped[List["CcctData"]] = db.relationship(back_populates="battery")
    ica_data: Mapped[List["IcaData"]] = db.relationship(back_populates="battery")
    left_border = mapped_column(db.Integer, nullable=True)
    right_border = mapped_column(db.Integer, nullable=True)
    stop_time = mapped_column(db.Integer, nullable=True)

    def __repr__(self) -> str:
        return f"Battery(id={self.id!r}, type = {self.bat_type!r}, ccct_data ={self.ccct_data!r}, ica_data = {self.ica_data!r}, , nominal charge = {self.nominal_charge!r})"


class CcctData(db.Model, TableNameMixin):

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

    id: Mapped[int] = mapped_column(primary_key=True)
    stap_charge: Mapped[float] = mapped_column(nullable=True)
    stap_voltage: Mapped[float]= mapped_column(nullable=True)
    timestamp: Mapped[datetime] = mapped_column()
    bat_id: Mapped[int] = mapped_column(db.ForeignKey("battery.id"))
    battery:Mapped["Battery"] = db.relationship(back_populates="ica_data")

    def __repr__(self) -> str:
        return f"Ica(id={self.id!r}, charge={self.stap_charge!r},  voltage = {self.stap_voltage!r}, time = {self.timestamp!r})"

class BattaryAnalizer:

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
        s: int = self.battery.parameters.filter_parameter
        unfilt = data['dQ/dV']
        unfiltar = unfilt.values
        data['G_Smoothed_dQ/dV'] = scipy.ndimage.gaussian_filter(unfiltar, sigma=s)
        return data

    
    def detect_peak_width(self, data: pd.DataFrame) -> list:
        w = list()
        peaks, _ = find_peaks(data['G_Smoothed_dQ/dV'])
        prominences = peak_prominences(data['G_Smoothed_dQ/dV'], peaks)[0]
        for i in range(0, len(peaks)):
            rel_h = (data['G_Smoothed_dQ/dV'][peaks].iloc[i] - prominences[i]) / data['G_Smoothed_dQ/dV'][peaks].iloc[i]
            rel_h = 1 - rel_h
            width = peak_widths(data['G_Smoothed_dQ/dV'], np.array(peaks[i]).reshape(1), rel_height=rel_h)
            w.append(width)
        return w, peaks

    
    # Повертає таблицю з даними для побудови IC
    def make_inc_curve(self, staps) -> pd.DataFrame:
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
        else:
            print("Waiting for data to set voltage borders!")

    
    def estimate_right_border(self) -> None:
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
        else:
            print("Waiting for data to set voltage borders!")





'''
Help functions

def create_user(self, name: str):
    user = User(name=name)
    db.session.add(user)
    db.session.commit()
    print(f"New user was created with the name: {name}")


def create_battery(self, user_name: str, bat_type: str, nominal_charge: float):
    id = select(User.id).where(User.name == user_name)
    user_id = db.session.scalar(id)
    battery = Battery(bat_type=bat_type, user_id=user_id)
    db.session.add(battery)
    db.session.commit()
    print(f"New battery was created with the battery type: {bat_type}")

def set_parameters(self, name: str):
    id = self.bat_id_by_name(name)
    battery = db.session.get(Battery, id)
    if battery.bat_type == 'a':
        battery.parameters = Parameters(first_icacycle=1, last_icacycle=2, first_ccctcycle=3,
                                            last_ccctcycle=10, ccct_cycles_stap=2, filter_parameter=3, peak=2,
                                            lmfit_model='linear')
        print(f"{name} battery parameters were updated, according to the battery type A")
    else:
        battery.parameters = Parameters(1, 2, 3, 1, 1, 1, 1, 'qubic')
        print(f"{name} battery parameters were updated, according to thr battery type B")

def insert_ica_data_by_name(self, name: str, charge: float, voltage: float):
    id = self.bat_id_by_name(name)
    db.session.execute(
        insert(IcaData).values(timestamp=func.now()).execution_options(render_nulls=True),
        {"stap_charge": charge, "stap_voltage": voltage, "bat_id": id},
    )
    print(f"User {name} resieved ica data")
    db.session.commit()

def bat_id_by_name(self, name: str):
    session = Session()
    with session as session:
        stmt = select(
            Bundle("user", User.name),
            Bundle("battery", Battery.id), ).join_from(User, Battery).where(User.name == name)
    for row in session.execute(stmt):
        return row.battery.id
            '''
