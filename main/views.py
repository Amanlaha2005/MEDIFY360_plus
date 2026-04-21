from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
import json
import random
from django.utils import timezone
from .ml_model import predict_diseases
from datetime import datetime
from google import genai
from .models import FitnessRecord
from .ml_fitness import calculate_risk
from .rag import search_knowledge
from .models import OTP, Profile, ChatMessage , Doctor , DoctorTiming , Appointment


# ================= INIT GEMINI =================
client = genai.Client(api_key=settings.GEMINI_API_KEY)

@csrf_exempt
def save_fitness(request):
    if request.method == "POST":
        data = json.loads(request.body)
        profile = request.user.profile
        bmi = profile.bmi
        age = profile.age
        bp = data.get("bp")
        chol = data.get("chol")

        risk = calculate_risk(age, bmi)

        FitnessRecord.objects.create(
            user=request.user,
            bmi=bmi,
            diabetes_risk=risk["diabetes"],
            heart_risk=risk["heart"],
            bp_risk=risk["bp"],
            chol_risk=risk["chol"],

            # ✅ SAVE REAL VALUES
            bp_value=bp,
            chol_value=chol
        )

        return JsonResponse({"status": "saved"})
    
def get_fitness(request):
    records = FitnessRecord.objects.filter(user=request.user).order_by("date")

    data = []

    for r in records:
        data.append({
            "bmi": r.bmi,
            "date": str(r.date),
            "diabetes": r.diabetes_risk,
            "heart": r.heart_risk,
            "bp": r.bp_value,
            "chol": r.chol_value
        })

    return JsonResponse({"records": data})
# ================= PERSONALITY =================
SYSTEM_PROMPT = """
You are a calm, emotionally intelligent, and caring big brother.

You talk like a real human, not like AI.

Your goal:
- Understand emotions deeply
- Respond with empathy first
- Then guide gently

Rules:
- Never give generic replies
- Always validate feelings
- Give small practical steps
- Be calm and human

Style:
1. Acknowledge feeling
2. Validate
3. Guide gently
"""


# ================= MEMORY =================
chat_memory = {}


# ================= FALLBACK =================
def local_fallback(msg):
    msg = msg.lower()

    if "sad" in msg:
        return "Hey… I can feel something’s bothering you 😔 You can talk to me."

    elif "nervous" in msg or "anxiety" in msg:
        return "Yeah… that nervous feeling is heavy 😟 Try slowing your breathing first."

    elif "brain" in msg or "overthinking" in msg:
        return "Your mind feels overloaded 🧠 Let’s pause… breathe… don’t rush."

    elif "what to do" in msg:
        return "Let’s go step by step 💙 First calm yourself, then we’ll figure it out."

    else:
        return "I’m here with you 💙 Take your time."


# ================= AI FUNCTION =================
def get_bot_response(user_id, message):
    try:
        history = chat_memory.get(user_id, [])
        history.append(f"User: {message}")

        # 🔥 RAG knowledge
        context = search_knowledge(message)

        prompt = (
            SYSTEM_PROMPT +
            "\n\nKnowledge:\n" + context +
            "\n\nConversation:\n" + "\n".join(history[-6:])
        )

        # ✅ NEW GEMINI API
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        reply = response.text if response.text else local_fallback(message)

        history.append(f"Brother: {reply}")
        chat_memory[user_id] = history[-10:]

        return reply

    except Exception as e:
        print("Gemini Error:", e)
        return local_fallback(message)


# ================= CHAT API =================
@csrf_exempt
def chat_api(request):
    if request.method == "POST":
        data = json.loads(request.body)
        message = data.get("message", "")

        if not message.strip():
            return JsonResponse({"reply": "Say something… I’m here 💙"})

        user_id = request.session.session_key
        if not user_id:
            request.session.save()
            user_id = request.session.session_key

        reply = get_bot_response(user_id, message)

        # save chat if logged in
        if request.user.is_authenticated:
            ChatMessage.objects.create(
                user=request.user,
                message=message,
                response=reply
            )

        return JsonResponse({"reply": reply})

    return JsonResponse({"error": "Invalid request"})


# ================= HOME =================
def home(request):
    return render(request, 'main/index.html')


def chatbot_page(request):
    return render(request, 'main/chatbot.html')

def get_dashboard_data(request):

    from .models import Profile, Doctor, Appointment, OPDBill, Staff, Driver

    total_citizens = Profile.objects.filter(role="CITIZEN").count()
    total_doctors = Doctor.objects.count()
    total_appointments = Appointment.objects.count()

    pending_staff = Staff.objects.filter(approval_status="pending").count()
    pending_driver = Driver.objects.filter(approval_status="pending").count()

    total_revenue = sum(b.net_amount for b in OPDBill.objects.all())

    return JsonResponse({
        "citizens": total_citizens,
        "doctors": total_doctors,
        "appointments": total_appointments,
        "pending": pending_staff + pending_driver,
        "revenue": total_revenue
    })
# ================= LOGIN =================
def login_user(request):
    if request.method == "POST":
        username_or_email = request.POST.get("username")
        password = request.POST.get("password")
        selected_role = request.POST.get("role")

        # 🔥 HANDLE EMAIL LOGIN
        if "@" in username_or_email:
            user_obj = User.objects.filter(email=username_or_email).first()
            if not user_obj:
                return JsonResponse({
                    "status": "error",
                    "message": "User not found"
                })
            username = user_obj.username
        else:
            username = username_or_email

        user = authenticate(request, username=username, password=password)

        if user is not None:

            # 🔥 SUPERUSER DIRECT LOGIN (IMPORTANT FIX)
            if user.is_superuser:
                login(request, user)
                return JsonResponse({
                    "status": "success",
                    "redirect": "/admin-dashboard/"
                })

            # 🔥 GET PROFILE FOR NORMAL USERS
            try:
                profile = Profile.objects.get(user=user)
                db_role = profile.role
            except Profile.DoesNotExist:
                return JsonResponse({
                    "status": "error",
                    "message": "Profile not found"
                })

            # ❌ ROLE MISMATCH
            if selected_role.upper() != db_role:
                return JsonResponse({
                    "status": "error",
                    "message": "Invalid credentials for selected role ❌"
                })

            # 🔥 STAFF APPROVAL
            try:
                staff = Staff.objects.get(user=user)

                if staff.approval_status == "pending":
                    return JsonResponse({
                        "status": "error",
                        "message": "Waiting for admin approval ❌"
                    })

                if staff.approval_status == "rejected":
                    return JsonResponse({
                        "status": "error",
                        "message": "Your request was rejected ❌"
                    })

            except Staff.DoesNotExist:
                pass

            # 🔥 DRIVER APPROVAL
            try:
                driver = Driver.objects.get(user=user)

                if driver.approval_status == "pending":
                    return JsonResponse({
                        "status": "error",
                        "message": "Waiting for admin approval ❌"
                    })

                if driver.approval_status == "rejected":
                    return JsonResponse({
                        "status": "error",
                        "message": "Your request was rejected ❌"
                    })

            except Driver.DoesNotExist:
                pass

            # ✅ LOGIN
            login(request, user)

            # 🔥 REDIRECT BASED ON ROLE
            if db_role == "ADMIN":
                return JsonResponse({
                    "status": "success",
                    "redirect": "/admin-dashboard/"
                })

            elif db_role == "STAFF":
                return JsonResponse({
                    "status": "success",
                    "redirect": "/staff-dashboard/"
                })

            elif db_role == "DRIVER":
                return JsonResponse({
                    "status": "success",
                    "redirect": "/staff-dashboard/"
                })

            elif db_role == "CITIZEN":
                return JsonResponse({
                    "status": "success",
                    "redirect": "/client-dashboard/"
                })

            else:
                return JsonResponse({
                    "status": "error",
                    "message": "Invalid role"
                })

        return JsonResponse({
            "status": "error",
            "message": "Invalid credentials"
        })

    return JsonResponse({"status": "error"})




def get_pending_requests(request):

    staff = Staff.objects.filter(approval_status="pending")
    drivers = Driver.objects.filter(approval_status="pending")

    staff_data = [{"id": s.id, "name": s.name} for s in staff]
    driver_data = [{"id": d.id, "name": d.name} for d in drivers]

    return JsonResponse({
        "staff": staff_data,
        "drivers": driver_data
    })
@csrf_exempt 
def approve_staff(request, id):
    staff = Staff.objects.get(id=id)
    staff.approval_status = "approved"
    staff.save()
    return JsonResponse({"status": "success"})


def reject_staff(request, id):
    staff = Staff.objects.get(id=id)
    staff.approval_status = "rejected"
    staff.save()
    return JsonResponse({"status": "success"})
def approve_driver(request, id):
    driver = Driver.objects.get(id=id)
    driver.approval_status = "approved"
    driver.save()
    return JsonResponse({"status": "success"})


def reject_driver(request, id):
    driver = Driver.objects.get(id=id)
    driver.approval_status = "rejected"
    driver.save()
    return JsonResponse({"status": "success"})
# ================= REGISTER =================
def register_user(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        role = request.POST.get("role")   # 🔥 ADD THIS

        if User.objects.filter(username=username).exists():
            return JsonResponse({"status": "error"})

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        profile, created = Profile.objects.get_or_create(user=user)

        # 🔥 SET ROLE PROPERLY
        profile.role = role.upper()
        profile.save()
        from .models import Staff

        if role.upper() == "STAFF":
            Staff.objects.create(
                user=user,
                name=username,
                email=email,
                approval_status="pending"
            )

        return JsonResponse({"status": "success"})

    return JsonResponse({"status": "error"})


# ================= DASHBOARDS =================
@login_required(login_url='/')
def admin_dashboard(request):
    return render(request, 'main/admin.html')


@login_required(login_url='/')
def staff_dashboard(request):
    return render(request, 'main/staff.html')


@login_required(login_url='/')
def client_dashboard(request):
    return render(request, 'main/client.html')


# ================= OTP =================
def send_otp(request):
    if request.method == "POST":
        email = request.POST.get("email")

        user = User.objects.filter(email=email).first()
        if not user:
            return JsonResponse({"status": "error"})

        OTP.objects.filter(user=user).delete()

        otp = str(random.randint(100000, 999999))
        OTP.objects.create(user=user, code=otp)

        send_mail(
            "OTP",
            f"Your OTP is {otp}",
            settings.EMAIL_HOST_USER,
            [email],
        )

        return JsonResponse({"status": "success"})

    return JsonResponse({"status": "error"})


def verify_otp(request):
    if request.method == "POST":
        email = request.POST.get("email")
        otp = request.POST.get("otp")

        user = User.objects.filter(email=email).first()
        otp_obj = OTP.objects.filter(user=user).first()

        if otp_obj and otp_obj.code == otp and not otp_obj.is_expired():
            return JsonResponse({"status": "success"})

        return JsonResponse({"status": "error"})

    return JsonResponse({"status": "error"})


def reset_password_otp(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        user = User.objects.filter(email=email).first()

        if user:
            user.set_password(password)
            user.save()
            OTP.objects.filter(user=user).delete()
            logout(request)

            return JsonResponse({"status": "success"})

    return JsonResponse({"status": "error"})


# ================= LOGOUT =================
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def logout_user(request):
    logout(request)
    return JsonResponse({"status": "success"})

from django.views.decorators.csrf import csrf_exempt
import json

# ADD CITIZEN
@csrf_exempt
def add_citizen(request):
    if request.method == "POST":
        data = json.loads(request.body)

        username = data.get("username")
        password = data.get("password")

        if User.objects.filter(username=username).exists():
            return JsonResponse({"status": "error", "message": "Username exists"})

        user = User.objects.create_user(
            username=username,
            password=password
        )

        # ✅ FIXED
        profile, created = Profile.objects.get_or_create(user=user)
        profile.role = "CITIZEN"
        profile.save()

        return JsonResponse({"status": "success"})

    return JsonResponse({"status": "error"})


# GET ALL CITIZENS
from django.db.models import Avg, Count

from django.contrib.auth.models import User
from django.db.models import Avg
from .models import Feedback

def get_citizens(request):

    citizens = User.objects.filter(profile__role="CITIZEN")

    data = []

    for user in citizens:

        feedbacks = Feedback.objects.filter(user=user)

        data.append({
            "id": user.id,
            "username": user.username,
            "avgRating": feedbacks.aggregate(Avg('rating'))['rating__avg'] or 0,
            "feedbackCount": feedbacks.count()
        })

    return JsonResponse({"citizens": data})

# DELETE CITIZEN
@csrf_exempt
def delete_citizen(request, id):
    user = User.objects.get(id=id)

    # ❌ NEVER delete admin
    if user.is_superuser:
        return JsonResponse({"status": "error", "message": "Cannot delete admin"})

    profile = Profile.objects.get(user=user)

    if profile.role != "CITIZEN":
        return JsonResponse({"status": "error", "message": "Not a citizen"})

    user.delete()
    return JsonResponse({"status": "success"})
@csrf_exempt
def add_doctor(request):

    if request.method == "POST":

        doctor_id = request.POST.get("id")
        name = request.POST.get("name")
        specialty = request.POST.get("specialty")
        experience = request.POST.get("experience")
        phone = request.POST.get("phone")
        image = request.FILES.get("image")  # 🔥 important

        if doctor_id:
            # UPDATE
            doc = Doctor.objects.get(id=doctor_id)
            doc.name = name
            doc.specialty = specialty
            doc.experience = experience
            doc.phone = phone

            if image:
                doc.image = image

            doc.save()

        else:
            # CREATE
            Doctor.objects.create(
                name=name,
                specialty=specialty,
                experience=experience,
                phone=phone,
                image=image
            )

        return JsonResponse({"status": "success"})

def get_doctors(request):
    doctors = Doctor.objects.all()

    data = []
    for d in doctors:
        data.append({
            "id": d.id,
            "name": d.name,
            "specialty": d.specialty,
            "experience": d.experience,
            "phone": d.phone,
            "image": d.image.url if d.image else ""
        })

    return JsonResponse({"doctors": data})

@csrf_exempt
def delete_doctor(request, id):
    Doctor.objects.filter(id=id).delete()
    return JsonResponse({"status": "success"})

@csrf_exempt
@csrf_exempt
def add_timing(request):
    if request.method == "POST":
        data = json.loads(request.body)

        doctor_id = data.get("doctorId")

# 🔥 SAFE CHECK
        try:
            doctor_id = int(doctor_id)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid doctor ID ❌"})

        doctor = Doctor.objects.get(id=doctor_id)

        timing_id = data.get("id")

# 🔥 SAFE CONVERSION
        try:
            timing_id = int(timing_id)
        except (TypeError, ValueError):
            timing_id = None

        booking_start = data.get("bookingStart")
        booking_end = data.get("bookingEnd")

        booking_start = data.get("bookingStart") or None
        booking_end = data.get("bookingEnd") or None

        if booking_start:
            booking_start = datetime.fromisoformat(booking_start)

        if booking_end:
            booking_end = datetime.fromisoformat(booking_end)

        start_time = datetime.strptime(data["startTime"], "%H:%M").time()
        end_time = datetime.strptime(data["endTime"], "%H:%M").time()

        
        DoctorTiming.objects.create(
            doctor=doctor,
            timing_type=data["type"],
            start_time=start_time,
            end_time=end_time,
            start_date = data.get("startDate") or None,
            end_date = data.get("endDate") or None,
            booking_start=booking_start,
            booking_end=booking_end,
        )

        return JsonResponse({"status": "success"})

    return JsonResponse({"status": "error"})
def get_timings(request):
    timings = DoctorTiming.objects.all()

    data = []
    for t in timings:
        data.append({
            "id":t.id,
            "doctor": t.doctor.name,
            "doctorId": t.doctor.id,  # 🔥 ADD THIS
            "type": t.timing_type,
            "startTime": str(t.start_time),
            "endTime": str(t.end_time),
            "startDate": str(t.start_date) if t.start_date else None,
            "endDate": str(t.end_date) if t.end_date else None,
            "bookingStart": str(t.booking_start) if t.booking_start else None,
            "bookingEnd": str(t.booking_end) if t.booking_end else None,
        })

    return JsonResponse({"timings": data})


from django.utils import timezone
from datetime import datetime
from django.views.decorators.csrf import csrf_exempt
import json

from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import datetime
import json

@csrf_exempt
def add_appointment(request):
    if request.method == "POST":
        data = json.loads(request.body)

        doctor = Doctor.objects.get(id=data["doctorId"])

        date_str = data.get("date")
        time_str = data.get("time")

        now = timezone.now()

        timings = DoctorTiming.objects.filter(doctor=doctor)

        # ❌ NO SCHEDULE
        if not timings.exists():
            return JsonResponse({"error": "schedule_not_set"})

        valid = False
        date = None
        time = None

        for t in timings:

            # =========================
            # 🔥 CASE 1: AUTO (NO DATE/TIME FROM CLIENT)
            # =========================
            if not date_str or not time_str:

                # use admin timing
                date = t.start_date if t.start_date else timezone.now().date()
                time = t.start_time

            else:
                # =========================
                # 🔥 CASE 2: NORMAL INPUT
                # =========================
                try:
                    date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except:
                    return JsonResponse({"error": "invalid_date"})

                try:
                    time = datetime.strptime(time_str, "%H:%M").time()
                except:
                    try:
                        time = datetime.strptime(time_str, "%H:%M:%S").time()
                    except:
                        return JsonResponse({"error": "invalid_time"})

            # =========================
            # ✅ REGULAR TIMING
            # =========================
            if t.timing_type == "REGULAR":
                if t.start_time <= time <= t.end_time:
                    valid = True

            # =========================
            # ✅ CUSTOM TIMING
            # =========================
            if t.timing_type == "CUSTOM":

                # 📅 Check date range
                if t.start_date and t.end_date:
                    if not (t.start_date <= date <= t.end_date):
                        continue

                # ⏰ Check time range
                if not (t.start_time <= time <= t.end_time):
                    continue

                # 🟡 Booking window
                if t.booking_start and t.booking_end:

                    booking_start = timezone.localtime(t.booking_start)
                    booking_end = timezone.localtime(t.booking_end)
                    current_time = timezone.localtime(now)

                    if current_time < booking_start:
                        return JsonResponse({"error": "not_started"})

                    elif current_time > booking_end:
                        return JsonResponse({"error": "closed"})

                    else:
                        valid = True

                else:
                    valid = True

        # ❌ NOT AVAILABLE
        if not valid:
            return JsonResponse({"error": "not_available"})

        # =========================
        # ✅ SAVE APPOINTMENT
        # =========================
        Appointment.objects.create(
            user=request.user,
            doctor=doctor,
            patient_name=data.get("patient"),
            date=date,
            time=time,
        )

        return JsonResponse({"status": "success"})

    return JsonResponse({"error": "invalid_request"})

from django.utils import timezone

def get_appointments(request):

    now = timezone.now()

    appts = Appointment.objects.filter(user=request.user)
    filtered = []

    for a in appts:

        appointment_datetime = datetime.combine(a.date, a.time)

        # ✅ Convert BOTH same way
        appointment_datetime = timezone.make_aware(
            appointment_datetime, timezone.get_current_timezone()
        )

        
        filtered.append({
            "id": a.id,
            "doctor": a.doctor.name,
            "doctorId": a.doctor.id,
            "patient": a.patient_name,
            "date": str(a.date),
            "time": str(a.time),
            "status": a.status
        })

    return JsonResponse({"appointments": filtered})
@csrf_exempt
def delete_timing(request, id):
    DoctorTiming.objects.filter(id=id).delete()
    return JsonResponse({"status": "success"})

import json
from django.http import JsonResponse
from .models import OPDBill, Doctor

from datetime import datetime

def save_opd_bill(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            doctor = Doctor.objects.get(id=data["doctor_id"])

            # 🔥 convert date
            date_obj = datetime.strptime(data["date"], "%Y-%m-%d").date()

            # 🔥 AUTO SERIAL
            last = OPDBill.objects.filter(date=date_obj, doctor=doctor).order_by('-serial_number').first()
            serial = last.serial_number + 1 if last else 1

            bill = OPDBill.objects.create(
                patient_name=data["patient_name"],
                doctor=doctor,
                serial_number=serial,   # ✅ AUTO GENERATED
                date=date_obj,

                fbs=data.get("fbs"),
                pbs=data.get("pbs"),
                bp=data.get("bp"),
                pulse=data.get("pulse"),
                weight=data.get("weight"),

                amount=data["amount"],
                discount=data.get("discount", 0),
                net_amount=data["net_amount"],
                payment_mode=data["payment_mode"]
            )

            return JsonResponse({
                "status": "success",
                "serial": serial   # 🔥 SEND BACK
            })

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})
        
        
def get_serial(request):
    doctor_id = request.GET.get("doctor_id")
    date = request.GET.get("date")

    doctor = Doctor.objects.get(id=doctor_id)

    date_obj = datetime.strptime(date, "%Y-%m-%d").date()

    last = OPDBill.objects.filter(doctor=doctor, date=date_obj).order_by('-serial_number').first()

    serial = last.serial_number + 1 if last else 1

    return JsonResponse({"serial": serial})

def get_opd_bills(request):
    name = request.GET.get("name")
    date = request.GET.get("date")

    bills = OPDBill.objects.all()

    # 🔥 FILTER BY NAME
    if name:
        bills = bills.filter(patient_name__icontains=name)

    # 🔥 FILTER BY DATE
    if date:
        bills = bills.filter(date=date)

    data = []
    for b in bills:
        data.append({
            "id": b.id,
            "patient": b.patient_name,
            "doctor": b.doctor.name,
            "doctorId": b.doctor.id,
            "amount": b.amount,
            "serial": b.serial_number,
            "date": str(b.date)
        })

    return JsonResponse({"bills": data})

from django.utils import timezone

def get_today_opd_bills(request):
    today = timezone.now().date()

    bills = OPDBill.objects.filter(date=today)

    data = []
    for b in bills:
        data.append({
            "id": b.id,
            "serial": b.serial_number,
            "patient": b.patient_name,
            "doctor": b.doctor.name,
            "amount": b.net_amount,
        })

    return JsonResponse({"bills": data})
@csrf_exempt
def delete_opd_bill(request, id):
    try:
        bill = OPDBill.objects.get(id=id)
        bill.delete()
        return JsonResponse({"status": "success"})
    except:
        return JsonResponse({"status": "error"})
    
from django.http import JsonResponse
import json
from .models import OPDBill , Staff , Driver

def update_opd_bill(request, id):
    if request.method == "POST":
        data = json.loads(request.body)

        try:
            bill = OPDBill.objects.get(id=id)

            bill.patient_name = data.get("patient_name")
            bill.doctor_id = data.get("doctor_id")
            bill.date = data.get("date")
            bill.amount = data.get("amount")
            bill.discount = data.get("discount")
            bill.net_amount = data.get("net_amount")

            bill.save()

            return JsonResponse({"status": "success"})
        except OPDBill.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Not found"})
        


def get_drivers(request):
    drivers = Driver.objects.all()

    data = []
    for d in drivers:
        data.append({
            "id": d.id,
            "name": d.name,
            "email": d.email,
            "phone": d.phone,
            "address": d.address,
            "image": d.image.url if d.image else "",
            "aadhaar": d.aadhaar.url if d.aadhaar else "",
            "license": d.license.url if d.license else "",
            "status": d.status
        })

    return JsonResponse({"drivers": data})

from django.utils import timezone

def check_doctor_status(request, doctor_id):

    now = timezone.localtime()   # 🔥 VERY IMPORTANT

    timings = DoctorTiming.objects.filter(doctor_id=doctor_id)

    if not timings.exists():
        return JsonResponse({"status": "schedule_not_set"})

    for t in timings:

        # ✅ REGULAR
        if t.timing_type == "REGULAR":
            return JsonResponse({"status": "open"})

        # ✅ CUSTOM
        if t.timing_type == "CUSTOM":

            if not t.booking_start or not t.booking_end:
                continue

            # 🔥 FORCE SAME TIMEZONE
            booking_start = timezone.localtime(t.booking_start)
            booking_end = timezone.localtime(t.booking_end)

            # DEBUG (optional)
            print("NOW:", now)
            print("START:", booking_start)

            # ⏳ BEFORE START
            if now < booking_start:
                return JsonResponse({
                    "status": "not_started",
                    "start": str(booking_start)
                })

            # ✅ THIS IS MOST IMPORTANT PART
            elif booking_start <= now <= booking_end:
                return JsonResponse({"status": "open"})

            # 🕒 AFTER END
            elif now > booking_end:
                return JsonResponse({
                    "status": "ended",
                    "start": str(booking_start),
                    "end": str(booking_end)
                })

    return JsonResponse({"status": "schedule_not_set"})
from .models import Feedback
@csrf_exempt
def add_feedback(request):
    if request.method == "POST":
        data = json.loads(request.body)

        Feedback.objects.create(
            user=request.user,
            
            rating=data["rating"],
            comment=data["comment"]
        )

        return JsonResponse({"status": "success"})
    
def get_feedbacks(request):

    if request.user.profile.role == "ADMIN":
        feedbacks = Feedback.objects.all()   # admin sees all
    else:
        feedbacks = Feedback.objects.filter(user=request.user)  # citizen sees own

    data = []

    for f in feedbacks:
        data.append({
            "patient": f.user.username,
            "rating": f.rating,
            "comment": f.comment
        })

    return JsonResponse({"feedbacks": data})
from django.views.decorators.csrf import csrf_exempt
def get_profile(request):
    profile = request.user.profile

    risk = None
    if profile.age and profile.bmi:
        risk = predict_diseases(profile.age, profile.bmi)

    return JsonResponse({
        "name": request.user.username,
        "email": request.user.email,
        "age": profile.age,
        "height": profile.height,
        "weight": profile.weight,
        "bmi": profile.bmi,
        "image": profile.image.url if profile.image else "",
        "family_phone": profile.family_phone,
        "risk": risk   # ✅ NEW
    })
    
@csrf_exempt
def update_profile(request):
    if request.method == "POST":
        data = json.loads(request.body)

        profile = request.user.profile

        age = data.get("age")
        height = data.get("height")
        weight = data.get("weight")
        family_phone = data.get("family_phone")

        # 🔥 SAVE PHONE FIRST
        profile.family_phone = family_phone

        if not height or not weight:
            profile.save()   # ✅ still save phone
            return JsonResponse({"error": "height_weight_required"})

        # BMI
        height_m = float(height) / 100
        bmi = float(weight) / (height_m ** 2)

        profile.age = age
        profile.height = height
        profile.weight = weight
        profile.bmi = round(bmi, 2)

        profile.save()   # ✅ FINAL SAVE

        return JsonResponse({"status": "success"})
@csrf_exempt
def upload_avatar(request):
    if request.method == "POST":

        image = request.FILES.get("image")

        if not image:
            return JsonResponse({"error": "no_image"})

        profile = request.user.profile
        profile.image = image   # make sure field exists
        profile.save()

        return JsonResponse({
            "status": "success",
            "image_url": profile.image.url
        })

    return JsonResponse({"error": "invalid"})

from django.utils import timezone
from django.http import JsonResponse
import json
from .models import StaffAttendance
@csrf_exempt
def start_staff_session(request):
    if request.method == "POST":

        # 🔥 CHECK IF ALREADY ACTIVE
        existing = StaffAttendance.objects.filter(
            staff=request.user,
            end_time__isnull=True
        ).first()

        if existing:
            return JsonResponse({
                "status": "already_active",
                "id": existing.id
            })

        attendance = StaffAttendance.objects.create(
            staff=request.user,
            start_time=timezone.now()
        )

        return JsonResponse({
            "status": "started",
            "id": attendance.id
        })

@csrf_exempt  
def end_staff_session(request):
    if request.method == "POST":
        data = json.loads(request.body)

        session_id = data.get("sessionId")

        try:
            attendance = StaffAttendance.objects.get(id=session_id)
        except:
            return JsonResponse({"error": "session_not_found"})

        end_time = timezone.now()

        duration = (end_time - attendance.start_time).total_seconds() / 3600

        attendance.end_time = end_time
        attendance.duration = round(duration, 4)
        attendance.save()

        return JsonResponse({"status": "ended"})
    
from django.utils import timezone
from datetime import timedelta
from collections import defaultdict

def get_staff_sessions(request):

    today = timezone.localdate()
    one_month_ago = today - timedelta(days=30)

    sessions = StaffAttendance.objects.filter(
        staff=request.user,
        start_time__date__gte=one_month_ago
    ).order_by("-start_time")

    # 🔥 ADD HERE (FILTER PART)
    date_filter = request.GET.get("date")
    month_filter = request.GET.get("month")

    if date_filter:
        sessions = sessions.filter(start_time__date=date_filter)

    if month_filter:
        year, month = month_filter.split("-")
        sessions = sessions.filter(
            start_time__year=year,
            start_time__month=month
        )
    grouped = defaultdict(lambda: {
        "total_hours": 0,
        "sessions": []
    })

    for s in sessions:
        date = timezone.localtime(s.start_time).strftime("%Y-%m-%d")

        duration = s.duration or 0

        grouped[date]["total_hours"] += duration

        grouped[date]["sessions"].append({
            "start": timezone.localtime(s.start_time).strftime("%Y-%m-%d %H:%M"),
            "end": timezone.localtime(s.end_time).strftime("%Y-%m-%d %H:%M") if s.end_time else None,
            "duration": round(duration, 2)
        })

    result = []
    today_str = timezone.localdate().strftime("%Y-%m-%d")
    for date, data in grouped.items():
        result.append({
            "date": date,
            "total_hours": round(data["total_hours"], 2),
            "sessions": data["sessions"],
            "is_today": (date == today_str)
        })

    return JsonResponse({"data": result})
from django.utils import timezone
from .models import StaffAttendance

def get_staff(request):
    from django.utils import timezone
    staff_list = Staff.objects.all()

    data = []

    for s in staff_list:

            active_session = StaffAttendance.objects.filter(
                staff=s.user,
                end_time__isnull=True
            ).first()

            sessions = StaffAttendance.objects.filter(staff=s.user)
            total_hours = sum([sess.duration for sess in sessions if sess.duration])

            today_sessions = StaffAttendance.objects.filter(
                staff=s.user,
                start_time__date=timezone.localdate()
            )

            from django.utils import timezone

            today_hours = 0

            for t in today_sessions:

                # ✅ Completed session
                if t.duration:
                    today_hours += t.duration

                # 🔥 LIVE SESSION (THIS WAS MISSING)
                elif t.start_time and not t.end_time:
                    now = timezone.now()
                    diff = (now - t.start_time).total_seconds() / 3600
                    today_hours += diff
            data.append({
                "email": s.email,
                "phone": s.phone,
                "address": s.address,
                "id": s.id,
                "name": s.name,
                "image": s.user.profile.image.url if s.user.profile.image else "",
                "today_hours": round(today_hours, 4),
                "hours": round(total_hours, 2),
                "approval_status": s.approval_status,
                "status": "Online" if active_session else "Offline"
            })

        # 🔥 RETURN OUTSIDE LOOP
    return JsonResponse({"staff": data})

from collections import defaultdict
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse

def get_staff_history(request, staff_id):

    from .models import Staff

    staff_obj = Staff.objects.get(id=staff_id)

    sessions = StaffAttendance.objects.filter(
        staff=staff_obj.user   # 🔥 CORRECT
    )

    # 🔥 FILTER
    date_filter = request.GET.get("date")
    month_filter = request.GET.get("month")

    if date_filter:
        sessions = sessions.filter(start_time__date=date_filter)

    elif month_filter:
        year, month = month_filter.split("-")
        sessions = sessions.filter(
            start_time__year=year,
            start_time__month=month
        )

    else:
        # 🔥 LAST 7 DAYS
        last_7 = timezone.now() - timedelta(days=7)
        sessions = sessions.filter(start_time__gte=last_7)

    # 🔥 GROUP DATA
    daily = defaultdict(float)

    for s in sessions:

        date = s.start_time.strftime("%Y-%m-%d")

        if s.duration:
            daily[date] += s.duration

        elif s.start_time and not s.end_time:
            now = timezone.now()
            diff = (now - s.start_time).total_seconds() / 3600
            daily[date] += diff

    # 🔥 CONVERT TO LIST
    data = [
        {"date": d, "hours": round(h, 2)}
        for d, h in daily.items()
    ]

    # 🔥 SORT
    data = sorted(data, key=lambda x: x["date"], reverse=True)
    print("SESSIONS:", sessions.count())
    print("DATA:", data)
    return JsonResponse({"history": data})







from django.utils import timezone

def get_current_session(request):
    session = StaffAttendance.objects.filter(
        staff=request.user,
        end_time__isnull=True
    ).order_by("-start_time").first()

    if session:
        return JsonResponse({
            "active": True,
            "id": session.id,
            "start_time": timezone.localtime(session.start_time).strftime("%Y-%m-%d %H:%M:%S"),
            "start_display": timezone.localtime(session.start_time).strftime("%I:%M %p")
        })
    else:
        return JsonResponse({
            "active": False
        })

from django.utils import timezone
from datetime import datetime, time

def get_today_hours(request):

    today = timezone.localdate()

    sessions = StaffAttendance.objects.filter(
        staff=request.user,
        start_time__date=today
    )

    total_hours = sum([s.duration for s in sessions if s.duration])

    return JsonResponse({
        "today_hours": round(total_hours, 2)
    })
    
from django.utils import timezone
from datetime import timedelta

def get_weekly_hours(request):

    today = timezone.localdate()
    days = []
    hours = []

    for i in range(6, -1, -1):
        day = today - timedelta(days=i)

        sessions = StaffAttendance.objects.filter(
            staff=request.user,
            start_time__date=day
        )

        total = sum([s.duration for s in sessions if s.duration])

        days.append(day.strftime("%a"))   # Mon, Tue
        hours.append(round(total, 2))

    return JsonResponse({
        "labels": days,
        "data": hours
    })
def get_last_session(request):

    session = StaffAttendance.objects.filter(
        staff=request.user,
        end_time__isnull=False
    ).order_by("-end_time").first()

    if not session:
        return JsonResponse({"exists": False})

    return JsonResponse({
        "exists": True,
        "duration": round(session.duration, 2),
        "end_time": timezone.localtime(session.end_time).strftime("%I:%M %p"),
        "date": timezone.localtime(session.end_time).strftime("%d %b")
    })

import csv
from django.http import HttpResponse
from django.utils import timezone

def export_attendance(request):

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="attendance.csv"'

    writer = csv.writer(response)
    writer.writerow(["Date", "Start Time", "End Time", "Duration (hrs)"])

    sessions = StaffAttendance.objects.filter(
        staff=request.user
    ).order_by("-start_time")

    for s in sessions:
        start = timezone.localtime(s.start_time).strftime("%Y-%m-%d %H:%M")
        end = timezone.localtime(s.end_time).strftime("%Y-%m-%d %H:%M") if s.end_time else "-"
        duration = s.duration if s.duration else 0

        writer.writerow([start.split(" ")[0], start.split(" ")[1], end, duration])

    return response

from django.views.decorators.csrf import csrf_exempt
import json
from .models import StaffMessage
@csrf_exempt
def send_message(request):
    data = json.loads(request.body)

    StaffMessage.objects.create(
        sender=request.user,
        message=data.get("message")
    )

    return JsonResponse({"status": "success"})

def get_messages(request):
    msgs = StaffMessage.objects.all().order_by("-timestamp")[:20]

    data = []
    for m in msgs:
        data.append({
            "user": m.sender.username,
            "msg": m.message,
            "time": m.timestamp.strftime("%H:%M")
        })

    return JsonResponse({"messages": data[::-1]})

def monthly_analytics(request):

    from django.utils import timezone
    from datetime import timedelta

    today = timezone.localdate()
    days = []
    hours = []

    for i in range(29, -1, -1):
        day = today - timedelta(days=i)

        sessions = StaffAttendance.objects.filter(
            staff=request.user,
            start_time__date=day
        )

        total = sum([s.duration for s in sessions if s.duration])

        days.append(day.strftime("%d"))
        hours.append(round(total, 2))

    return JsonResponse({
        "labels": days,
        "data": hours
    })

from django.db.models.functions import TruncDate

def performance_score(request):

    from django.utils import timezone
    from datetime import timedelta

    today = timezone.localdate()
    last_30 = today - timedelta(days=30)

    sessions = StaffAttendance.objects.filter(
        staff=request.user,
        start_time__date__gte=last_30
    )

    total_hours = sum([s.duration for s in sessions if s.duration])

    # 🔥 COUNT ACTIVE DAYS
    active_days = sessions.annotate(
        day=TruncDate("start_time")
    ).values("day").distinct().count()

    # 🔥 SAFE CALCULATION
    max_hours = active_days * 8 if active_days else 1

    percentage = (total_hours / max_hours) * 100

    return JsonResponse({
        "score": round(percentage, 2)
    })

@csrf_exempt
def send_location(request):
    data = json.loads(request.body)
    lat = data.get("lat")
    lon = data.get("lon")

    print(f"Location: {lat}, {lon}")

    return JsonResponse({"status": "received"})

import requests

from django.views.decorators.csrf import csrf_exempt
import json
import requests

import requests
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def emergency_alert(request):
    if request.method == "POST":

        data = json.loads(request.body)
        lat = data.get("lat")
        lon = data.get("lon")

        profile = request.user.profile
        number = profile.family_phone

        # ❗ check if number exists
        if not number:
            return JsonResponse({"error": "No phone number saved"})

        # ✅ FIX NUMBER FORMAT (VERY IMPORTANT)
        number = "91" + number

        # ✅ SIMPLE MESSAGE (for testing)
        message = "Emergency Alert! Please help."

        url = "https://www.fast2sms.com/dev/bulkV2"

        payload = {
            "sender_id": "FSTSMS",
            "message": message,
            "language": "english",
            "route": "q",
            "numbers": number
        }

        headers = {
            "authorization": "8LPm6kJM77307EIU6ggEGz6nTWn5w6vzBP7Cyqm499iTRDQ4yOioxFpKt8mT",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers)

        # ✅ DEBUG OUTPUT (VERY IMPORTANT)
        print("SMS RESPONSE:", response.text)

        return JsonResponse({"status": "sent"})
    
@csrf_exempt
def get_ai_diet(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            age = data.get("age")
            bmi = data.get("bmi")
            bp = data.get("bp")
            chol = data.get("chol")

            prompt = f"""
                Give ONLY diet in this format:

                Breakfast:
                Lunch:
                Dinner:

                Age: {age}
                BMI: {bmi}
                BP: {bp}
                Cholesterol: {chol}
                """

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            return JsonResponse({
                "diet": response.text
            })

        except:
            # 🔥 NO ERROR SHOWN
            return JsonResponse({
                "diet": "Breakfast: Oats + Fruits | Lunch: Dal + Rice + Sabzi | Dinner: Roti + Vegetables"
            })   
        
        
        
        
        
@csrf_exempt
def get_ai_exercise(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            bmi = data.get("bmi")

            prompt = f"""
Give ONLY exercise plan:

Morning:
Evening:

BMI: {bmi}
"""

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            return JsonResponse({
                "exercise": response.text
            })

        except:
            return JsonResponse({
                "exercise": "Morning: 30 min walking | Evening: Light yoga + stretching"
            })