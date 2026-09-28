def html_table(viz, env, args):
    headers = [
        "name",
        "age",
        "position",
        "salary"
    ]
    data = [
        ["abc", 24, "ml eng", "90k"],
        ["pqr", 29, "backend dev", "110k"],
    ]
    viz.html_table(
        headers=headers,
        data=data,
        env=env,
        opts={
            "title": "employee table"
        }
    )

def table(viz, env, args):
    headers = ["Name", "Score", "City"]
    rows = [
        ["alpha", 92, "Delhi"],
        ["beta", 85, "Mumbai"],
        ["charlie", 78, "Pune"],
    ]
    viz.table(
        data=rows,
        headers=headers,
        env=env,
        opts={"title": "Leaderboard"},
    )
