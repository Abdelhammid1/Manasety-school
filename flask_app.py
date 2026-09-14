from app import create_app
from app.extensions import db
from app.models import (
    School, User, Role, AcademicYear, Term, Grade, Section,
)

app = create_app()


@app.shell_context_processor
def shell_ctx():
    return {
        "db": db,
        "School": School,
        "User": User,
        "Role": Role,
        "AcademicYear": AcademicYear,
        "Term": Term,
        "Grade": Grade,
        "Section": Section,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
