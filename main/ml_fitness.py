def calculate_risk(age, bmi):

    # simple ML-like logic (good enough for project)
    diabetes = min(100, int(bmi * 2))
    heart = min(100, int((age/2) + bmi))
    bp = min(100, int(bmi + 20))
    chol = min(100, int(bmi + 15))

    return {
        "diabetes": diabetes,
        "heart": heart,
        "bp": bp,
        "chol": chol
    }