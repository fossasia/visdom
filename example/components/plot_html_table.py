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
    viz.table(
        headers=headers,
        data=data,
        env=env,
        opts={
            "title": "employee table"
        }
    )
