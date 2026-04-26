from django import forms
from django.contrib.auth.hashers import check_password
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator

from .models import HiveUser

username_validator = RegexValidator(
    regex=r"^[A-Za-z0-9_]+$",
    message="닉네임은 영문, 숫자, 밑줄(_)만 사용할 수 있습니다.",
)


class SignUpForm(forms.Form):
    username = forms.CharField(
        label="닉네임",
        min_length=3,
        max_length=16,
        validators=[username_validator],
    )
    email = forms.EmailField(label="이메일", max_length=255)
    password = forms.CharField(
        label="비밀번호", min_length=8, widget=forms.PasswordInput
    )
    password_confirm = forms.CharField(
        label="비밀번호 확인", widget=forms.PasswordInput
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {
                "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                "placeholder": "hive_member",
                "autofocus": True,
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                "placeholder": "name@example.com",
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                "placeholder": "8자 이상",
            }
        )
        self.fields["password_confirm"].widget.attrs.update(
            {
                "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                "placeholder": "비밀번호를 다시 입력하세요",
            }
        )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if HiveUser.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("이미 사용 중인 닉네임입니다.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if HiveUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("이미 가입된 이메일입니다.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "비밀번호가 일치하지 않습니다.")
        if password:
            candidate_user = HiveUser(username=username or "", email=email or "")
            try:
                validate_password(password, user=candidate_user)
            except forms.ValidationError as error:
                self.add_error("password", error)
        return cleaned_data


class LoginForm(forms.Form):
    email = forms.EmailField(label="이메일", max_length=255)
    password = forms.CharField(label="비밀번호", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(
            {
                "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                "placeholder": "name@example.com",
                "autofocus": True,
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                "placeholder": "••••••••",
            }
        )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class ProfileEditForm(forms.ModelForm):
    class Meta:
        model = HiveUser
        fields = ["username", "email", "profile_image"]
        labels = {
            "username": "닉네임",
            "email": "이메일",
            "profile_image": "프로필 이미지 URL",
        }
        widgets = {
            "username": forms.TextInput(),
            "email": forms.EmailInput(),
            "profile_image": forms.URLInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].validators.append(username_validator)
        self.fields["username"].widget.attrs.update(
            {
                "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                "placeholder": "hive_member",
                "maxlength": 16,
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                "placeholder": "name@example.com",
            }
        )
        self.fields["profile_image"].required = False
        self.fields["profile_image"].widget.attrs.update(
            {
                "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                "placeholder": "https://example.com/avatar.png",
            }
        )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = HiveUser.objects.filter(username__iexact=username)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("이미 사용 중인 닉네임입니다.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = HiveUser.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("이미 가입된 이메일입니다.")
        return email


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        label="현재 비밀번호",
        widget=forms.PasswordInput,
    )
    new_password = forms.CharField(
        label="새 비밀번호",
        min_length=8,
        widget=forms.PasswordInput,
    )
    new_password_confirm = forms.CharField(
        label="새 비밀번호 확인",
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, user: HiveUser, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        for field_name, placeholder in {
            "current_password": "현재 비밀번호를 입력하세요",
            "new_password": "8자 이상",
            "new_password_confirm": "새 비밀번호를 다시 입력하세요",
        }.items():
            self.fields[field_name].widget.attrs.update(
                {
                    "class": "w-full rounded-2xl border-stone-200 bg-white px-4 py-3",
                    "placeholder": placeholder,
                }
            )

    def clean_current_password(self):
        current_password = self.cleaned_data["current_password"]
        if not self.user.password_hash or not check_password(
            current_password, self.user.password_hash
        ):
            raise forms.ValidationError("현재 비밀번호가 올바르지 않습니다.")
        return current_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        new_password_confirm = cleaned_data.get("new_password_confirm")
        current_password = cleaned_data.get("current_password")

        if (
            new_password
            and new_password_confirm
            and new_password != new_password_confirm
        ):
            self.add_error("new_password_confirm", "새 비밀번호가 일치하지 않습니다.")

        if current_password and new_password and current_password == new_password:
            self.add_error(
                "new_password", "현재 비밀번호와 다른 비밀번호를 사용하세요."
            )

        if new_password:
            try:
                validate_password(new_password, user=self.user)
            except forms.ValidationError as error:
                self.add_error("new_password", error)

        return cleaned_data
