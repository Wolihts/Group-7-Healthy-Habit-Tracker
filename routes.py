"""! \file routes.py
\brief Healthy Habit Tracker – Flask routes and helpers.

This module defines the web routes (login, register, sleep, diet, workout, goals, feedback)
and helper functions for database access and chart data.

It is documented for Doxygen via the **doxypypy** filter. Docstring fields use
Sphinx/Napoleon style (``:param:`` / ``:returns:``) which doxypypy converts for Doxygen.
"""

import psycopg2
from flask import Flask, render_template, request, redirect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash


def get_db_connection():
    """Open and return a new psycopg2 connection to the production database.

    :returns: A new open psycopg2 connection.
    """
    return psycopg2.connect(
        host="uno-habittracker.cxa4qcikgs1o.us-east-2.rds.amazonaws.com",
        dbname="habit_tracker",
        user="postgres",
        password="WOpIwqP2g2EnD2m",
        port=5432
    )


# --- (one-time) connection sanity check / legacy init ---
conn = get_db_connection()
cur = conn.cursor()
conn.commit()
cur.close()
conn.close()


class User(UserMixin):
    """Simple Flask-Login user wrapper backed by the database.

    :param id: The user's database id (user_detail_id).
    :type id: int | str
    """

    def __init__(self, id):
        self.id = str(id)
        self.username = self.get_username()

    def get_id(self):
        """Return the user id string for Flask-Login.

        :returns: The user id as a string.
        :rtype: str
        """
        return self.id

    def get_username(self):
        """Lookup and return the username for this user id.

        :returns: The username or ``None`` on error.
        :rtype: str | None
        """
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT user_detail_username FROM habits.user_detail WHERE user_detail_id = %s",
                (self.id,)
            )
            username = cur.fetchone()[0]
            cur.close()
            conn.close()
            return username
        except (Exception, psycopg2.Error) as error:
            print(f"Error while getting username: {error}")
            return None


def get_data(table_name):
    """Retrieve all rows from a given habits table for the current user.

    :param table_name: Table name without schema (e.g. ``'sleep'``, ``'workout'``).
    :type table_name: str
    :returns: List of tuples from the query, newest first; empty list on error.
    :rtype: list[tuple]
    """
    conn = get_db_connection()
    cur = conn.cursor()
    query = f"SELECT * FROM habits.{table_name} WHERE user_detail_id = %s ORDER BY {table_name}_date DESC"
    try:
        cur.execute(query, (current_user.id,))
        rows = cur.fetchall()
        return rows
    except psycopg2.Error as e:
        print(f"Database error in get_data for table '{table_name}': {e}")
        return []
    finally:
        cur.close()
        conn.close()


def _get_feedback_for_user(limit=20):
    """Fetch recent feedback records for the current user.

    :param limit: Max number of rows to return (default 20).
    :type limit: int
    :returns: List of feedback tuples (ordered by created_at DESC).
    :rtype: list[tuple]
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            feedback_id,
            feedback_type,
            feedback_page,
            feedback_message,
            COALESCE(feedback_rating, 0),
            contact_email,
            created_at
        FROM habits.feedback
        WHERE user_detail_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (current_user.id, limit),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_chart_data(table_name, date_column, value_column):
    """Get (date, value) pairs for a chart from a given table.

    :param table_name: Table (without schema) containing the data.
    :type table_name: str
    :param date_column: Name of the date column.
    :type date_column: str
    :param value_column: Name of the numeric/value column.
    :type value_column: str
    :returns: List of (date, value) tuples sorted by date ASC; empty list on error.
    :rtype: list[tuple]
    """
    conn = get_db_connection()
    cur = conn.cursor()
    query = (
        f"SELECT {date_column}, {value_column} "
        f"FROM habits.{table_name} WHERE user_detail_id = %s ORDER BY {date_column}"
    )
    try:
        cur.execute(query, (current_user.id,))
        rows = cur.fetchall()
        return rows
    except psycopg2.Error as e:
        print(f"Database error in get_chart_data for table '{table_name}': {e}")
        return []
    finally:
        cur.close()
        conn.close()


def get_goal_data():
    """Fetch the user's current goals row.

    :returns: List of goal rows (usually 0 or 1 entry).
    :rtype: list[tuple]
    """
    conn = get_db_connection()
    cur = conn.cursor()
    query = "SELECT * FROM habits.goals WHERE user_detail_id = %s"
    try:
        cur.execute(query, (current_user.id,))
        rows = cur.fetchall()
        return rows
    except psycopg2.Error as e:
        print(f"Database error in get_data for table 'goals': {e}")
        return []
    finally:
        cur.close()
        conn.close()


def diet_tips(diet_data, goal_data):
    """Compute diet tips based on user logs vs goal.

    :param diet_data: Rows from ``habits.diet`` for the user.
    :type diet_data: list[tuple]
    :param goal_data: Rows from ``habits.goals`` for the user.
    :type goal_data: list[tuple]
    :returns: A list of human-readable tip strings.
    :rtype: list[str]
    """
    tips = []
    if diet_data == [] or goal_data == []:
        tips.append("Not enough data yet...")
        return tips
    diets = 0
    diet_avg = 0
    newest = diet_data[0][4]
    goal = goal_data[0][4]
    for diet in diet_data:
        diet_avg += diet[4]
        diets += 1
    diet_avg = diet_avg / diets
    if diet_avg >= goal:
        tips.append(f"Your Average ({diet_avg:.2f}) currently meets or is passing your goal!")
    else:
        tips.append(f"Your Average ({diet_avg:.2f}) is currently below your goal!")
    if newest >= goal:
        tips.append(f"Your newest ({newest}) is above your goal! Keep it up!")
    else:
        tips.append(f"Your newest ({newest}) is below your goal! Don't let this become a trend.")
    return tips


def workout_tips(work_data, goal_data):
    """Compute workout tips based on user logs vs goal.

    :param work_data: Rows from ``habits.workout`` for the user.
    :type work_data: list[tuple]
    :param goal_data: Rows from ``habits.goals`` for the user.
    :type goal_data: list[tuple]
    :returns: A list of human-readable tip strings.
    :rtype: list[str]
    """
    tips = []
    if work_data == [] or goal_data == []:
        tips.append("Not enough data yet...")
        return tips
    works = 0
    work_avg = 0
    newest = work_data[0][4]
    goal = goal_data[0][3]
    for work in work_data:
        work_avg += work[4]
        works += 1
    work_avg = work_avg / works
    if work_avg >= goal:
        tips.append(f"Your Average intensity ({work_avg:.2f}) currently meets or is passing your goal!")
    else:
        tips.append(f"Your Average intensity ({work_avg:.2f}) is currently below your goal!")
        tips.append("If you're using weights, try increasing the weight or amount of reps.")
    if newest >= goal:
        tips.append(f"Your most recent intensity ({newest}) meets or is above your goal!")
        if newest >= 8:
            tips.append("Try not to go too intense too often; it's okay to take a break occasionally.")
    else:
        tips.append(f"Your newest ({newest}) is below your goal!")
        tips.append("If you're taking a break that's okay, but try to increase the intensity when you're ready.")
    return tips


def sleep_tips(sleep_data, goal_data):
    """Compute sleep tips based on user logs vs goal.

    :param sleep_data: Rows from ``habits.sleep`` for the user.
    :type sleep_data: list[tuple]
    :param goal_data: Rows from ``habits.goals`` for the user.
    :type goal_data: list[tuple]
    :returns: A list of human-readable tip strings.
    :rtype: list[str]
    """
    tips = []
    if sleep_data == [] or goal_data == []:
        tips.append("Not enough data yet...")
        return tips
    sleeps = 0
    sleep_len_avg = 0
    sleep_qual_avg = 0
    newest_len = sleep_data[0][1]
    newest_qual = sleep_data[0][4]
    goal_len = goal_data[0][1]
    goal_qual = goal_data[0][2]
    for sleep in sleep_data:
        sleep_len_avg += sleep[1]
        sleep_qual_avg += sleep[4]
        sleeps += 1
    sleep_len_avg = sleep_len_avg / sleeps
    sleep_qual_avg = sleep_qual_avg / sleeps
    if sleep_len_avg >= goal_len:
        tips.append(f"Your Average length of sleep ({sleep_len_avg:.2f}) currently meets or is passing your goal!")
    else:
        tips.append(f"Your Average length of sleep ({sleep_len_avg:.2f}) is currently below your goal!")
    if newest_len >= goal_len:
        tips.append(f"Your newest length of sleep ({newest_len}) is above your goal! Keep it up!")
    else:
        tips.append(f"Your newest length of sleep ({newest_len}) is below your goal! Don't let this become a trend.")
    if sleep_qual_avg >= goal_qual:
        tips.append(f"Your average quality of sleep({sleep_qual_avg:.2f}) is above your goal! Keep it up!")
    else:
        tips.append(f"Your average quality of sleep ({sleep_qual_avg:.2f}) is currently below your goal!")
        tips.append("For better sleep quality, try not to use any screens for at least an hour before bed.")
    if newest_qual >= goal_qual:
        tips.append(f"Your most recent sleep ({newest_qual}) meets or is above your goal!")
    else:
        tips.append(f"Your most recent sleep ({newest_qual}) is below your goal!")
    return tips


# ---------------------------
# Flask App + Routes
# ---------------------------

app = Flask(__name__)
app.secret_key = 'your_secret_key'

login_manager = LoginManager(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    """Load a user by id for Flask-Login.

    :param user_id: The user_detail_id to load.
    :type user_id: int | str
    :returns: A ``User`` instance or ``None``.
    :rtype: User | None
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM habits.user_detail WHERE user_detail_id = %s', (user_id,))
    user_data = cur.fetchone()
    conn.close()
    if user_data:
        return User(id=user_data[0])
    return None


@app.route("/")
@login_required
def index():
    """Home page.

    **Methods:** GET
    """
    return render_template("home.html", user=current_user.username)


# -------- Auth --------

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log a user in.

    **Methods:** GET, POST

    POST form fields: ``username``, ``password``.
    """
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM habits.user_detail WHERE user_detail_username = %s', (username,))
        user_data = cur.fetchone()
        conn.close()

        if user_data and check_password_hash(user_data[2], password):
            user = User(id=user_data[0])
            login_user(user)
            return redirect('/')
        else:
            return render_template('login.html', error="Incorrect username or password")
    return render_template('login.html')


@app.route("/register", methods=["GET", "POST"])
def register():
    """Create a new account.

    **Methods:** GET, POST

    POST form fields: ``username``, ``password``.
    """
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute('SELECT 1 FROM habits.user_detail WHERE user_detail_username = %s', (username,))
        existing_user = cur.fetchone()
        if existing_user:
            conn.close()
            return render_template('signup.html', error='Username taken!')

        cur.execute(
            'INSERT INTO habits.user_detail (user_detail_username, user_detail_password) VALUES (%s, %s)',
            (username, password_hash)
        )
        conn.commit()
        conn.close()
        return redirect('/login')
    return render_template('signup.html')


@app.route('/logout')
@login_required
def logout():
    """Log the current user out.

    **Methods:** GET
    """
    logout_user()
    return redirect('/login')


# -------- Habits --------

@app.route("/sleep", methods=["GET", "POST"])
@login_required
def sleep():
    """Create and list sleep entries.

    **Methods:** GET, POST

    POST fields: ``date``, ``duration``, ``rating``, ``notes``.
    """
    if request.method == 'POST':
        date = request.form.get('date')
        duration = request.form.get('duration')
        rating = request.form.get('rating')
        notes = request.form.get('notes')

        user_id = current_user.get_id()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO habits.sleep (
                sleep_duration, sleep_date, sleep_log, sleep_rating, user_detail_id
            ) VALUES (%s, %s, %s, %s, %s);
            """,
            (duration, date, notes, rating, user_id),
        )
        conn.commit()
        cur.close()
        conn.close()

    sleep_data = get_data("sleep")
    goal_data = get_goal_data()
    tips = sleep_tips(sleep_data, goal_data)
    sleep_chart_data = get_chart_data("sleep", "sleep_date", "sleep_duration")
    return render_template(
        "sleep.html",
        sleep_data=sleep_data,
        sleep_chart_data=sleep_chart_data,
        tips=tips,
        user=current_user.username,
    )


@app.route("/diet", methods=["GET", "POST"])
@login_required
def diet():
    """Create and list diet entries.

    **Methods:** GET, POST

    POST fields: ``date``, ``rating``, ``mealname``, ``notes``.
    """
    if request.method == 'POST':
        date = request.form.get('date')
        rating = request.form.get('rating')
        mealname = request.form.get('mealname')
        mealnotes = request.form.get('notes')

        user_id = current_user.get_id()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO habits.diet (
                diet_name, diet_date, diet_log, diet_rating, user_detail_id
            ) VALUES (%s, %s, %s, %s, %s);
            """,
            (mealname, date, mealnotes, rating, user_id),
        )
        conn.commit()
        cur.close()
        conn.close()

    diet_data = get_data("diet")
    goals = get_goal_data()
    tips = diet_tips(diet_data, goals)
    diet_chart_data = get_chart_data("diet", "diet_date", "diet_rating")
    return render_template(
        "diet.html",
        diet_data=diet_data,
        diet_chart_data=diet_chart_data,
        tips=tips,
        user=current_user.username,
    )


@app.route("/workout", methods=["GET", "POST"])
@login_required
def workout():
    """Create and list workout entries.

    **Methods:** GET, POST

    POST fields: ``date``, ``name``, ``duration``, ``intensity``, ``type``, ``rating``, ``notes``.
    """
    if request.method == 'POST':
        date = request.form.get('date')
        name = request.form.get('name')
        duration = request.form.get('duration')
        intensity = request.form.get('intensity')
        type = request.form.get('type')
        rating = request.form.get('rating')
        notes = request.form.get('notes')

        user_id = current_user.get_id()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO habits.workout (
                workout_name, workout_date, workout_duration, workout_intensity,
                workout_type, workout_log, workout_rating, user_detail_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (name, date, duration, intensity, type, notes, rating, user_id),
        )
        conn.commit()
        cur.close()
        conn.close()

    workout_data = get_data("workout")
    goal_data = get_goal_data()
    tips = workout_tips(workout_data, goal_data)
    workout_chart_data = get_chart_data("workout", "workout_date", "workout_duration")
    return render_template(
        "workout.html",
        workout_data=workout_data,
        workout_chart_data=workout_chart_data,
        tips=tips,
        user=current_user.username,
    )


@app.route('/goals', methods=['GET', 'POST'])
@login_required
def goals():
    """Create/update and view goals.

    **Methods:** GET, POST

    POST fields: ``duration`` (sleep_len_goal), ``quality`` (better_sleep),
    ``intense`` (intensity), ``diet`` (diet).
    """
    if request.method == 'POST':
        moresleep = request.form.get('duration')
        bettersleep = request.form.get('quality')
        intensity = request.form.get('intense')
        diet = request.form.get('diet')
        user_id = current_user.get_id()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO habits.goals(sleep_len_goal, better_sleep, intensity, diet, user_detail_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_detail_id)
            DO UPDATE SET
                sleep_len_goal = EXCLUDED.sleep_len_goal,
                better_sleep   = EXCLUDED.better_sleep,
                intensity      = EXCLUDED.intensity,
                diet           = EXCLUDED.diet
            """,
            (moresleep, bettersleep, intensity, diet, user_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    return render_template("goals.html", user=current_user.username)


@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    """Submit and list in-app feedback.

    **Methods:** GET, POST

    POST fields: ``type`` (bug|idea|praise), ``page`` (home|sleep|workout|diet|other),
    ``message``, ``rating`` (1–5), ``email`` (optional).
    """
    if request.method == "POST":
        ftype  = (request.form.get("type") or "").strip().lower()
        fpage  = (request.form.get("page") or "").strip().lower()
        msg    = (request.form.get("message") or "").strip()
        rating = request.form.get("rating")
        email  = (request.form.get("email") or "").strip()

        # safe rating coercion
        try:
            r_val = int(rating) if rating else None
            if r_val is not None and not (1 <= r_val <= 5):
                r_val = None
        except ValueError:
            r_val = None

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO habits.feedback (
                user_detail_id, feedback_type, feedback_page,
                feedback_message, feedback_rating, contact_email
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (current_user.id, ftype, fpage, msg, r_val, email if email else None),
        )
        conn.commit()
        cur.close()
        conn.close()
        return redirect("/feedback")

    fb_rows = _get_feedback_for_user()
    return render_template("feedback.html", user=current_user.username, feedback_data=fb_rows)


# -------- Errors --------

@app.errorhandler(404)
def page_not_found(e):
    """404 Not Found handler."""
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_error(e):
    """500 Internal Server Error handler."""
    return render_template("500.html"), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=11596, debug=True)
