from datetime import UTC

from django import forms
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .community_content import build_post_markdown
from .models import (
    Comment,
    CommentStatus,
    Post,
    PostStatus,
    Source,
    Tag,
    TagType,
    WikiDocument,
    WikiDocumentStatus,
)

FORM_INPUT_CLASS = "w-full rounded-2xl border-stone-200 bg-white px-4 py-3"
FORM_TEXTAREA_CLASS = "w-full rounded-2xl border-stone-200 bg-white px-4 py-3 leading-7"


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


class PostForm(forms.Form):
    draft_id = forms.UUIDField(required=False, widget=forms.HiddenInput())
    body_markdown = forms.CharField(
        label="본문",
        widget=forms.Textarea(attrs={"rows": 12}),
    )
    tag_names = forms.CharField(
        label="태그",
        required=False,
        help_text="쉼표로 구분해 최대 5개까지 입력할 수 있습니다.",
    )
    wiki_documents = forms.ModelMultipleChoiceField(
        label="연결할 위키 문서",
        queryset=WikiDocument.objects.none(),
        required=False,
        help_text="관련 위키를 선택해 두면 게시글과 문서가 함께 연결됩니다.",
        widget=forms.CheckboxSelectMultiple(),
    )
    status = forms.ChoiceField(
        label="공개 상태",
        choices=[
            (PostStatus.PUBLISHED, "게시"),
            (PostStatus.DRAFT, "임시 저장"),
        ],
        initial=PostStatus.PUBLISHED,
    )

    def __init__(self, *args, **kwargs):
        wiki_document_queryset = kwargs.pop("wiki_document_queryset", None)
        super().__init__(*args, **kwargs)
        if wiki_document_queryset is None:
            wiki_document_queryset = WikiDocument.objects.filter(
                status=WikiDocumentStatus.PUBLISHED,
                current_revision__isnull=False,
            ).order_by("-updated_at", "title")
        self.fields["wiki_documents"].queryset = wiki_document_queryset
        self.fields["body_markdown"].widget.attrs.update(
            {
                "class": FORM_TEXTAREA_CLASS,
                "placeholder": "지금 필요한 질문이나 생각을 바로 적어보세요.",
                "data-community-compose-body": "true",
            }
        )
        self.fields["tag_names"].widget.attrs.update(
            {
                "class": FORM_INPUT_CLASS,
                "placeholder": "예: 검색, 온보딩, UX",
                "data-community-tag-input": "true",
            }
        )
        self.fields["wiki_documents"].widget.attrs.update(
            {"data-community-wiki-selector": "true"}
        )
        self.fields["status"].widget.attrs.update({"class": FORM_INPUT_CLASS})

    def clean_body_markdown(self):
        body_markdown = self.cleaned_data["body_markdown"].strip()
        if not body_markdown:
            raise forms.ValidationError("본문을 입력해 주세요.")
        return body_markdown

    def clean_tag_names(self):
        raw_value = self.cleaned_data["tag_names"]
        tag_names: list[str] = []
        seen_names: set[str] = set()
        for item in raw_value.split(","):
            cleaned_name = " ".join(item.strip().split())
            if not cleaned_name:
                continue
            if not slugify(cleaned_name, allow_unicode=True):
                raise forms.ValidationError("태그에는 문자나 숫자가 포함되어야 합니다.")
            normalized_name = cleaned_name.casefold()
            if normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)
            tag_names.append(cleaned_name[:50])

        if len(tag_names) > 5:
            raise forms.ValidationError("태그는 최대 5개까지 입력할 수 있습니다.")
        return tag_names

    def clean_wiki_documents(self):
        wiki_documents = list(self.cleaned_data["wiki_documents"])
        if len(wiki_documents) > 10:
            raise forms.ValidationError("위키 문서는 최대 10개까지 연결할 수 있습니다.")
        return wiki_documents

    @transaction.atomic
    def save(self, *, author_user, instance=None):
        if instance is None:
            post = Post.objects.create(
                author_user=author_user,
                content_markdown=build_post_markdown(
                    self.cleaned_data["body_markdown"]
                ),
                status=self.cleaned_data["status"],
            )
        else:
            post = instance
            post.author_user = author_user
            post.content_markdown = build_post_markdown(
                self.cleaned_data["body_markdown"]
            )
            post.status = self.cleaned_data["status"]
            post.updated_at = timezone.now()
            post.save(
                update_fields=[
                    "author_user",
                    "content_markdown",
                    "status",
                    "updated_at",
                ]
            )
        tags = [
            self._get_or_create_tag(name) for name in self.cleaned_data["tag_names"]
        ]
        post.tags.set(tags)
        post.wiki_documents.set(self.cleaned_data["wiki_documents"])
        return post

    def _get_or_create_tag(self, name: str) -> Tag:
        existing_tag = Tag.objects.filter(name__iexact=name).first()
        if existing_tag is not None:
            return existing_tag

        base_slug = slugify(name, allow_unicode=True)
        if not base_slug:
            raise forms.ValidationError("태그 슬러그를 생성할 수 없습니다.")

        slug = base_slug
        suffix = 2
        while Tag.objects.filter(slug__iexact=slug).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        return Tag.objects.create(
            name=name,
            slug=slug,
            tag_type=TagType.USER,
        )


class CommentForm(forms.ModelForm):
    parent_comment_id = forms.UUIDField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Comment
        fields = ["content", "parent_comment_id"]
        labels = {"content": "댓글"}
        widgets = {"content": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["content"].widget.attrs.update(
            {
                "class": FORM_TEXTAREA_CLASS,
                "placeholder": "질문에 답하거나 논의를 이어가 보세요.",
            }
        )

    def clean_content(self):
        content = self.cleaned_data["content"].strip()
        if not content:
            raise forms.ValidationError("댓글 내용을 입력해 주세요.")
        return content

    def clean_parent_comment_id(self):
        return self.cleaned_data["parent_comment_id"]

    def save(self, *, post, author_user, parent_comment=None, commit=True):
        comment = super().save(commit=False)
        comment.post = post
        comment.author_user = author_user
        comment.parent_comment = parent_comment
        comment.status = CommentStatus.PUBLISHED
        if commit:
            comment.save()
        return comment
