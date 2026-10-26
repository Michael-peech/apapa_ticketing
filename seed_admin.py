from database import SessionLocal, engine
import models
from passlib.context import CryptContext

# Force create all tables (including the new 'users' table)
models.Base.metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
db = SessionLocal()

admin_email = "admin@olamagri.com"
admin_password = "SecurePassword123!"

existing_user = db.query(models.User).filter(models.User.email == admin_email).first()

if not existing_user:
    new_admin = models.User(
        email=admin_email,
        hashed_password=pwd_context.hash(admin_password),
        role=models.UserRole.ADMIN,
        department="IT Operations"
    )
    db.add(new_admin)
    db.commit()
    print(f"Master admin created! Email: {admin_email} | Password: {admin_password}")
else:
    print("Admin account already exists.")

db.close()
