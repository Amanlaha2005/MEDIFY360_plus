import numpy as np
from sklearn.linear_model import LogisticRegression

# -------------------------
# TRAIN MODELS
# -------------------------

X = np.array([
    [25, 22], [40, 28], [55, 32], [60, 35], [30, 24],
    [45, 29], [50, 31], [65, 36], [35, 26]
])

# Labels for different diseases
y_diabetes = [0,0,1,1,0,0,1,1,0]
y_heart    = [0,0,1,1,0,1,1,1,0]
y_bp       = [0,0,1,1,0,1,1,1,0]
y_chol     = [0,0,1,1,0,1,1,1,0]

# Create models
diabetes_model = LogisticRegression().fit(X, y_diabetes)
heart_model    = LogisticRegression().fit(X, y_heart)
bp_model       = LogisticRegression().fit(X, y_bp)
chol_model     = LogisticRegression().fit(X, y_chol)


# -------------------------
# HELPER FUNCTION
# -------------------------
def format_result(prob):
    percent = int(prob * 100)

    if percent >= 70:
        status = "🔴 High"
    elif percent >= 40:
        status = "🟠 Moderate"
    else:
        status = "🟢 Low"

    return percent, status


# -------------------------
# MAIN PREDICTION
# -------------------------
def predict_diseases(age, bmi):

    data = [[age, bmi]]

    d_prob = diabetes_model.predict_proba(data)[0][1]
    h_prob = heart_model.predict_proba(data)[0][1]
    bp_prob = bp_model.predict_proba(data)[0][1]
    c_prob = chol_model.predict_proba(data)[0][1]

    d_per, d_status = format_result(d_prob)
    h_per, h_status = format_result(h_prob)
    bp_per, bp_status = format_result(bp_prob)
    c_per, c_status = format_result(c_prob)

    return {
        "diabetes": f"{d_per}% {d_status}",
        "heart": f"{h_per}% {h_status}",
        "bp": f"{bp_per}% {bp_status}",
        "cholesterol": f"{c_per}% {c_status}"
    }