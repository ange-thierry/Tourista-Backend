from django.db import models


class ContactMessage(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField()
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name}: {self.subject or self.message[:40]}'


class DemoRequest(models.Model):
    full_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    company = models.CharField(max_length=200, blank=True)
    stakeholder_type = models.CharField(max_length=40, blank=True)
    business_size = models.CharField(max_length=100, blank=True)
    preferred_date = models.DateField()
    preferred_time = models.CharField(max_length=20)
    attendees = models.CharField(max_length=20, blank=True)
    specific_needs = models.TextField(blank=True)
    current_challenges = models.TextField(blank=True)
    goals = models.TextField(blank=True)
    additional_info = models.TextField(blank=True)
    handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.full_name} · {self.preferred_date} {self.preferred_time}'
