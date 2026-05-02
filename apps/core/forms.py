from datetime import UTC

from django import forms
from django.utils import timezone
from django.utils.text import slugify

from .models import Source, Tag, TagType

FORM_INPUT_CLASS = "w-full rounded-2xl border-stone-200 bg-white px-4 py-3"


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ["name", "slug", "tag_type"]
        labels = {
            "name": "태그 이름",
            "slug": "슬러그",
            "tag_type": "태그 유형",
        }
        widgets = {
            "name": forms.TextInput(),
            "slug": forms.TextInput(),
            "tag_type": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        if not self.instance.pk and not self.is_bound:
            self.initial.setdefault("tag_type", TagType.SYSTEM)
        self.fields["name"].widget.attrs.update(
            {
                "class": FORM_INPUT_CLASS,
                "placeholder": "예: 디자인 시스템",
                "maxlength": 50,
            }
        )
        self.fields["tag_type"].widget.attrs.update({"class": FORM_INPUT_CLASS})
        self.fields["slug"].widget.attrs.update(
            {
                "class": FORM_INPUT_CLASS,
                "placeholder": "예: design-system",
                "maxlength": 50,
            }
        )

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_slug(self):
        raw_slug = self.cleaned_data["slug"].strip()
        if not raw_slug:
            raw_slug = self.cleaned_data.get("name", "")
        normalized_slug = slugify(raw_slug, allow_unicode=True)
        if not normalized_slug:
            raise forms.ValidationError("슬러그를 생성할 수 없습니다.")

        qs = Tag.objects.filter(slug__iexact=normalized_slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("이미 사용 중인 슬러그입니다.")
        return normalized_slug


class SourceForm(forms.ModelForm):
    next_poll_at = forms.DateTimeField(
        label="다음 수집 시각",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )

    class Meta:
        model = Source
        fields = [
            "name",
            "target_url",
            "enabled",
            "poll_interval_minutes",
            "next_poll_at",
        ]
        labels = {
            "name": "소스 이름",
            "target_url": "대상 URL",
            "enabled": "활성화",
            "poll_interval_minutes": "수집 주기(분)",
        }
        widgets = {
            "name": forms.TextInput(),
            "target_url": forms.URLInput(),
            "enabled": forms.CheckboxInput(),
            "poll_interval_minutes": forms.NumberInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.update(
            {
                "class": FORM_INPUT_CLASS,
                "placeholder": "예: 커뮤니티 공지 피드",
            }
        )
        self.fields["target_url"].widget.attrs.update(
            {
                "class": FORM_INPUT_CLASS,
                "placeholder": "https://example.com/feed",
            }
        )
        self.fields["poll_interval_minutes"].widget.attrs.update(
            {
                "class": FORM_INPUT_CLASS,
                "min": 1,
                "step": 1,
            }
        )
        self.fields["next_poll_at"].widget.attrs.update(
            {
                "class": FORM_INPUT_CLASS,
                "data-local-datetime-input": "true",
            }
        )
        self.fields["enabled"].widget.attrs.update(
            {
                "class": "h-5 w-5 rounded border-stone-300 text-primary focus:ring-primary-container",
            }
        )

        if self.instance.pk and self.instance.next_poll_at:
            initial_value = timezone.localtime(self.instance.next_poll_at).strftime(
                "%Y-%m-%dT%H:%M"
            )
            self.initial.setdefault("next_poll_at", initial_value)
            self.fields["next_poll_at"].widget.attrs["data-local-datetime-source"] = (
                self.instance.next_poll_at.astimezone(UTC).isoformat()
            )
        elif not self.is_bound and not self.initial.get("next_poll_at"):
            current_time = timezone.now()
            self.initial["next_poll_at"] = timezone.localtime(current_time).strftime(
                "%Y-%m-%dT%H:%M"
            )
            self.fields["next_poll_at"].widget.attrs["data-local-datetime-source"] = (
                current_time.astimezone(UTC).isoformat()
            )

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_poll_interval_minutes(self):
        poll_interval_minutes = self.cleaned_data["poll_interval_minutes"]
        if poll_interval_minutes < 1:
            raise forms.ValidationError("수집 주기는 1분 이상이어야 합니다.")
        return poll_interval_minutes

    def clean_target_url(self):
        return self.cleaned_data["target_url"].strip()
