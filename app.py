from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "sprint1_secret"

def get_db():
    conn = sqlite3.connect('vps.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        zone TEXT NOT NULL,
        vehicle_type TEXT NOT NULL,
        is_occupied BOOLEAN DEFAULT 0
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS parking_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_number TEXT NOT NULL,
        slot_id INTEGER NOT NULL,
        entry_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        exit_time DATETIME,
        FOREIGN KEY(slot_id) REFERENCES slots(id)
    )''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    filter_type = request.args.get('type')
    conn = get_db()
    query = "SELECT * FROM slots"
    params = ()
    if filter_type in ['two-wheeler', 'four-wheeler']:
        query += " WHERE vehicle_type = ?"
        params = (filter_type,)
    slots = conn.execute(query, params).fetchall()
    
    # Group by zone
    zones = {}
    for slot in slots:
        zones.setdefault(slot['zone'], []).append(slot)
        
    return render_template('index.html', zones=zones, filter_type=filter_type)

@app.route('/admin')
def admin():
    conn = get_db()
    slots = conn.execute('SELECT * FROM slots').fetchall()
    return render_template('admin.html', slots=slots)

@app.route('/admin/add', methods=['POST'])
def add_slot():
    name = request.form.get('name')
    zone = request.form.get('zone')
    v_type = request.form.get('vehicle_type')
    conn = get_db()
    conn.execute('INSERT INTO slots (name, zone, vehicle_type) VALUES (?, ?, ?)', (name, zone, v_type))
    conn.commit()
    flash(f"Slot {name} added to {zone}.", "success")
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:slot_id>', methods=['POST'])
def delete_slot(slot_id):
    conn = get_db()
    # Basic check if occupied
    slot = conn.execute('SELECT is_occupied FROM slots WHERE id = ?', (slot_id,)).fetchone()
    if slot and slot['is_occupied']:
        flash("Cannot remove an occupied slot.", "danger")
    else:
        conn.execute('DELETE FROM slots WHERE id = ?', (slot_id,))
        conn.commit()
        flash("Slot removed successfully.", "success")
    return redirect(url_for('admin'))

@app.route('/entry', methods=['GET', 'POST'])
def entry():
    conn = get_db()
    if request.method == 'POST':
        vehicle_number = request.form.get('vehicle_number')
        slot_id = request.form.get('slot_id')
        
        conn.execute('INSERT INTO parking_logs (vehicle_number, slot_id) VALUES (?, ?)', (vehicle_number, slot_id))
        conn.execute('UPDATE slots SET is_occupied = 1 WHERE id = ?', (slot_id,))
        conn.commit()
        flash(f"Entry recorded for {vehicle_number}.", "success")
        return redirect(url_for('entry'))
        
    available_slots = conn.execute('SELECT * FROM slots WHERE is_occupied = 0').fetchall()
    return render_template('entry.html', available_slots=available_slots)

@app.route('/exit', methods=['GET'])
def exit_list():
    conn = get_db()
    query = '''SELECT pl.id as log_id, pl.vehicle_number, pl.entry_time, s.name as slot_name, s.zone, s.vehicle_type 
               FROM parking_logs pl 
               JOIN slots s ON pl.slot_id = s.id 
               WHERE pl.exit_time IS NULL'''
    active_logs = conn.execute(query).fetchall()
    return render_template('exit.html', active_logs=active_logs)

@app.route('/exit/<int:log_id>', methods=['POST'])
def record_exit(log_id):
    conn = get_db()
    log = conn.execute('SELECT slot_id FROM parking_logs WHERE id = ?', (log_id,)).fetchone()
    if log:
        conn.execute('UPDATE parking_logs SET exit_time = CURRENT_TIMESTAMP WHERE id = ?', (log_id,))
        conn.execute('UPDATE slots SET is_occupied = 0 WHERE id = ?', (log['slot_id'],))
        conn.commit()
        flash("Exit recorded successfully.", "success")
    return redirect(url_for('exit_list'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
