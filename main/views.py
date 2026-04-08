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
from datetime import datetime
from google import genai
from .rag import search_knowledge
from .models import OTP, Profile, ChatMessage , Doctor , DoctorTiming , Appointment


# ================= INIT GEMINI =================
client = genai.Client(api_key=settings.GEMINI_API_KEY)


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
        role = request.POST.get("role")

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

            # 🔥 STAFF APPROVAL CHECK
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

            # 🔥 DRIVER APPROVAL CHECK
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

            # ✅ LOGIN ONLY AFTER APPROVAL
            login(request, user)

            # 🔥 ADMIN LOGIN
            if role == "Admin":
                if user.is_superuser:
                    return JsonResponse({
                        "status": "success",
                        "redirect": "/admin-dashboard/"
                    })
                else:
                    return JsonResponse({
                        "status": "error",
                        "message": "You are not admin"
                    })

            # 🔥 STAFF LOGIN
            elif role == "Staff":
                return JsonResponse({
                    "status": "success",
                    "redirect": "/staff-dashboard/"
                })

            # 🔥 DRIVER LOGIN (OPTIONAL)
            elif role == "Driver":
                return JsonResponse({
                    "status": "success",
                    "redirect": "/staff-dashboard/"
                })

            # 🔥 CITIZEN LOGIN
            else:
                return JsonResponse({
                    "status": "success",
                    "redirect": "/client-dashboard/"
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

        if User.objects.filter(username=username).exists():
            return JsonResponse({"status": "error"})

        user = User.objects.create_user(username=username, email=email, password=password)
        Profile.objects.get_or_create(user=user)

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
def get_citizens(request):
    citizens = Profile.objects.filter(role="CITIZEN")

    data = []

    for p in citizens:
        data.append({
            "id": p.user.id,
            "username": p.user.username,
            "email": p.user.email,
            "role": p.role,

            # 🔥 NEW
            "avgRating": 0,        # later connect feedback DB
            "feedbackCount": 0
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

@csrf_exempt
def add_appointment(request):
    if request.method == "POST":
        data = json.loads(request.body)

        doctor = Doctor.objects.get(id=data["doctorId"])

        date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        time_str = data["time"]

        try:
            # try HH:MM
            time = datetime.strptime(time_str, "%H:%M").time()
        except:
            # fallback HH:MM:SS
            time = datetime.strptime(time_str, "%H:%M:%S").time()

        timings = DoctorTiming.objects.filter(doctor=doctor)

        if not timings.exists():
            return JsonResponse({"error": "Doctor timing not set ❌"})

        valid = False
        now = timezone.now()

        for t in timings:

            # ✅ REGULAR
            if t.timing_type == "REGULAR":
                if t.start_time <= time <= t.end_time:
                    valid = True

            # ✅ CUSTOM
            if t.timing_type == "CUSTOM":
                if t.start_date and t.end_date:
                    if t.start_date <= date <= t.end_date:

                        if t.start_time <= time <= t.end_time:

                            if t.booking_start and t.booking_end:
                                if t.booking_start <= now <= t.booking_end:
                                    valid = True
                                else:
                                    continue  # 🔥 DON'T RETURN HERE
                            else:
                                valid = True

        if not valid:
            return JsonResponse({"error": "Booking not started or doctor not available ❌"})
        Appointment.objects.create(
            doctor=doctor,
            patient_name=data["patient"],
            date=date,
            time=time,
        )

        return JsonResponse({"status": "success"})

    return JsonResponse({"error": "Invalid request"})

from django.utils import timezone

def get_appointments(request):
    now = timezone.now()

    appts = Appointment.objects.all()

    filtered = []

    for a in appts:
        appointment_datetime = timezone.make_aware(
            datetime.combine(a.date, a.time)
        )

        if appointment_datetime >= now:
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
        
def get_staff(request):
    staff = Staff.objects.all()

    data = []
    for s in staff:
        data.append({
            "id": s.id,
            "name": s.name,
            "email": s.email,
            "phone": s.phone,
            "address": s.address,
            "image": s.image.url if s.image else "",
            "aadhaar": s.aadhaar.url if s.aadhaar else "",
            "status": s.status
        })

    return JsonResponse({"staff": data})

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