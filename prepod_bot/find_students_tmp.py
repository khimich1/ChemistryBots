import sys
from services.groups import get_all_students_with_plans, is_student_in_group


def _norm(u: str) -> str:
    u = (u or "").strip()
    if u.startswith("@"):  # strip leading @
        u = u[1:]
    return u.lower()


def main(usernames: list[str]) -> int:
    wanted = {_norm(u) for u in usernames if u}
    students = get_all_students_with_plans()

    found = []
    for s in students:
        uname = (s.get("username") or "").lstrip("@")
        if _norm(uname) in wanted:
            s["in_group"] = is_student_in_group(s["user_id"])  # bool
            found.append(s)

    if not found:
        print("Никого не нашли.")
        return 1

    for s in found:
        label = s.get("label") or f"ID {s['user_id']}"
        uname = s.get("username") or ""
        plan = s.get("plan_code") or "free"
        in_group = "да" if s.get("in_group") else "нет"
        print(f"- {label}  (@{uname})  id={s['user_id']}  тариф={plan}  в_группе={in_group}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Использование: python find_students_tmp.py @username1 @username2 ...")
        sys.exit(2)
    sys.exit(main(args))


