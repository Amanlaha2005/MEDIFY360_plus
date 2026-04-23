from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

class OTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=5)

    def __str__(self):
        return f"{self.user.username} - {self.code}"

class Profile(models.Model):
    ROLE_CHOICES = (
        ('ADMIN', 'Admin'),
        ('STAFF', 'Staff'),
        ('CITIZEN', 'Citizen'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='CITIZEN')
    image = models.ImageField(upload_to='profile/', null=True, blank=True)
    age = models.IntegerField(null=True, blank=True)
    height = models.FloatField(null=True, blank=True)
    weight = models.FloatField(null=True, blank=True)
    bmi = models.FloatField(null=True, blank=True)
    family_phone = models.CharField(max_length=15, blank=True, null=True)
    coins = models.IntegerField(default=0)
    
    def __str__(self):
        return f"{self.user.username} - {self.role}"
    
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
        
User.add_to_class('profile', property(lambda u: Profile.objects.get(user=u)))

class ChatMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_msgs",blank=True,null=True)
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_msgs",null=True,blank=True)

    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True,null=True,blank=True)

    is_read = models.BooleanField(default=False)
    
class Doctor(models.Model):
    image = models.ImageField(upload_to='doctors/', null=True, blank=True)
    name = models.CharField(max_length=100)
    specialty = models.CharField(max_length=100)
    experience = models.IntegerField()
    phone = models.CharField(max_length=15)

    def __str__(self):
        return self.name

class DoctorTiming(models.Model):
    TIMING_TYPE = (
        ('REGULAR', 'Regular'),
        ('CUSTOM', 'Custom'),
    )

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)

    timing_type = models.CharField(max_length=10, choices=TIMING_TYPE)

    # 🔹 Common (both)
    start_time = models.TimeField()
    end_time = models.TimeField()

    # 🔹 Only for CUSTOM
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # 🔹 Booking control (CUSTOM only)
    booking_start = models.DateTimeField(null=True, blank=True)
    booking_end = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.doctor.name} - {self.timing_type}"
    
from django.contrib.auth.models import User

class Appointment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)  # 🔥 ADD THIS
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    patient_name = models.CharField(max_length=100)
    date = models.DateField()
    time = models.TimeField()
    status = models.CharField(max_length=20, default="pending")
    def __str__(self):
        return f"{self.patient_name} - {self.doctor.name}"
    
class OPDBill(models.Model):
    patient_name = models.CharField(max_length=100)
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)

    serial_number = models.IntegerField()
    date = models.DateField()

    fbs = models.CharField(max_length=50, blank=True, null=True)
    pbs = models.CharField(max_length=50, blank=True, null=True)
    bp = models.CharField(max_length=50, blank=True, null=True)
    pulse = models.CharField(max_length=50, blank=True, null=True)
    weight = models.CharField(max_length=50, blank=True, null=True)

    amount = models.FloatField()
    discount = models.FloatField(default=0)
    net_amount = models.FloatField()

    payment_mode = models.CharField(max_length=20)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.patient_name
    
class Staff(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE , null=True , blank=True)

    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    address = models.TextField()

    image = models.ImageField(upload_to='staff/', null=True, blank=True)
    aadhaar = models.ImageField(upload_to='aadhaar/', null=True, blank=True)

    # 🔥 IMPORTANT
    status = models.CharField(max_length=10, default="absent")  # active / absent
    approval_status = models.CharField(max_length=10, default="pending")  # pending / approved / rejected

    def __str__(self):
        return self.name
    
class Driver(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True , blank=True)

    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    address = models.TextField()

    image = models.ImageField(upload_to='drivers/', null=True, blank=True)
    aadhaar = models.ImageField(upload_to='aadhaar/', null=True, blank=True)
    license = models.ImageField(upload_to='license/', null=True, blank=True)

    status = models.CharField(max_length=10, default="absent")
    approval_status = models.CharField(max_length=10, default="pending")

    def __str__(self):
        return self.name
    
class Feedback(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField()
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
class StaffAttendance(models.Model):
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    duration = models.FloatField(default=0)  # in hours

    def __str__(self):
        return f"{self.staff.username} - {self.start_time}"
    
class StaffMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
class FitnessRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    bmi = models.FloatField()

    diabetes_risk = models.FloatField()
    heart_risk = models.FloatField()
    bp_risk = models.FloatField()
    chol_risk = models.FloatField()

    # ✅ ADD THESE
    bp_value = models.CharField(max_length=20, null=True, blank=True)
    chol_value = models.IntegerField(null=True, blank=True)

    date = models.DateTimeField(auto_now_add=True)
    
class Category(models.Model):
    name = models.CharField(max_length=100,unique=True)

    def __str__(self):
        return self.name


class Medicine(models.Model):
    name = models.CharField(max_length=200)
    image = models.ImageField(upload_to="medicines/")
    quantity = models.IntegerField()
    unit = models.CharField(max_length=50, default="strip",blank=True,null=True)
    mrp = models.FloatField(default=0)

    category = models.ForeignKey(Category, on_delete=models.CASCADE)

    def __str__(self):
        return self.name
    
# ================= CART SYSTEM =================

class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    city = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)
    full_address = models.TextField()

class Cart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)

class Order(models.Model):
    STATUS = (
        ("pending", "Pending"),
        ("ongoing", "Ongoing"),
        ("delivered", "Delivered")
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    address = models.ForeignKey(Address, on_delete=models.CASCADE)
    total = models.FloatField()
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    price = models.FloatField()

class CoinClaim(models.Model):
    CLAIM_TYPES = (
        ('BMI', 'BMI Improvement'),
        ('DOCTOR', 'Doctor Visit'),
        ('RISK', 'Risk Reduction'),
        ('PROFILE', 'Profile Completion'),
    )
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('CLAIMED', 'Claimed'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    claim_type = models.CharField(max_length=20, choices=CLAIM_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'claim_type')

    def __str__(self):
        return f"{self.user.username} - {self.claim_type} ({self.status})"
    
class Contact(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)