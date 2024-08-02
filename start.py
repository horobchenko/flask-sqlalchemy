from __future__ import annotations
from flask_login import login_user, login_required, logout_user
from sqlalchemy import event
from app.models import *
from flask import Flask, render_template, redirect, flash, url_for
from flask import request
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, app


@app.route( '/')
def index():
    return render_template('index.html')

@app.route ( '/submit' , methods= [ 'GET', 'POST'] )
def submit():
    if request.method == 'POST':
        try:
            hash = generate_password_hash(request.form['password'])
            name = request.form['name']
            user = User(name = name, password = hash)
            db.session.add(user)
            db.session.flush()
            bat_type = request.form['bat_type']
            battery = Battery(bat_type = bat_type, nominal_charge = 0.1, user_id = user.id)
            db.session.add(battery)
            db.session.flush()
            if bat_type == 'a':
                battery.parameters = Parameters(first_icacycle=1, last_icacycle=2, first_ccctcycle=3,
                                                last_ccctcycle=10, ccct_cycles_stap=2, filter_parameter=3, peak=2,
                                                lmfit_model='linear')
            elif bat_type == 'b':
                battery.parameters = Parameters(1, 2, 3, 1, 1, 1, 1, 'quadratic')
            else:
                battery.parameters = Parameters(1, 2, 3, 1, 1, 1, 1, 'qubic')
            db.session.commit()
            flash('Вітаємо! Ви пройшли реєстрацію')
            return redirect(url_for('login'))
        except:
            db.session.rollback()
            flash('Вітаємо! Спробуйте ще раз..щось пішло не так')
            print("Помилка завантаження даних!")
    return render_template('registration.html')

@app.route('/login', methods = ['GET', 'POST'])
def login():
    login = request.form.get('name')
    password = request.form.get('password')
    if login and password:
        if login == 'admin' and password == 1234:
            return redirect(url_for('admin_page', login=login))
        else:
            user = User.query.filter_by(name = login).first()
            if user and check_password_hash(user.password, password):
                login_user(user)
                return redirect(url_for('user_page', login = login))
            else:
                flash('Будь-ласка, введіть правильний логін та пароль!')
    return render_template('login.html')

@app.route('/admin_page', methods = ['GET', 'POST'])
#@login_required
def admin_page():
    users = User.query.all()
    t = list()
    c = list()
    stmt = db.select(Battery.bat_type, db.func.count(Battery.id)).group_by(Battery.bat_type)
    for type, count in db.session.execute(stmt):
       t.append(type)
       c.append(count)
    print(c)
    print(t)
    return render_template('admin_page.html', users = users, c = c, type = t)


@app.route('/delete_user', methods = ['POST'])
def delete_user():
    if request.method =="POST":
        user = request.form['name']
        u = User.query.filter_by(name=user).first()
        db.session.delete(u)
        db.session.commit()
        flash(f'Користувач {user} видалений з бази!')
        return redirect(url_for('admin_page'))

@app.route('/user_page/<login>', methods = ['GET'])
@login_required
def user_page(login):
    def ica_data_analize(login):
        bat = BattaryAnalizer(login, db.session)
        bat.estimate_left_border()
        bat.estimate_right_border()

    def ccct_data_analize(login):
        bat = BattaryAnalizer(login, db.session)
        bat.estimate_stop_time()

    event.listen(Battery.ica_data, 'append', ica_data_analize)
    event.listen(Battery.ccct_data, 'append', ccct_data_analize)

    stmt = db.select(Battery.stop_time).join_from(User, Battery).where(User.name == login)
    stop_time = db.session.scalar(stmt)
    if stop_time is None:
        text = 'Додаток збирає дані для аналізу стану батареї'
    else:
        stmt_2 = db.select(CcctData.ccct_time).join_from(Battery, CcctData)
        current_time = db.session.scalars(stmt_2).all()
        for item in current_time:
            if item is not None and not current_time:
                text = 'Аналіз стану акумулятора завершено. Ваш акумулятор знаходиться в робочому стані!'
            else:
                text = 'Ваш акумулятор потрібно негайно замінити! Будь-ласка, зверніться до сервісного центру'
    return render_template('user_page.html', login = login, text = text)

@app.route('/logout', methods = ['GET', 'POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='127.0.0.1',port=54238 , debug=False)



'''
db.init_app(app)
with app.app_context():
    db.create_all()
'''