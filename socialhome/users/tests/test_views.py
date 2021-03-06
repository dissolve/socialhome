import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.urlresolvers import reverse
from django.test import RequestFactory

from socialhome.content.models import Content
from socialhome.content.tests.factories import ContentFactory
from socialhome.enums import Visibility
from socialhome.tests.utils import SocialhomeTestCase
from socialhome.users.models import User, Profile
from socialhome.users.tables import FollowedTable
from socialhome.users.tests.factories import UserFactory, AdminUserFactory, ProfileFactory
from socialhome.users.views import (
    ProfileUpdateView, ProfileDetailView, OrganizeContentProfileDetailView, ProfileAllContentView)


class TestProfileUpdateView(SocialhomeTestCase):
    def setUp(self):
        # call BaseUserTestCase.setUp()
        super(TestProfileUpdateView, self).setUp()
        self.user = self.make_user()
        self.factory = RequestFactory()
        # Instantiate the view directly. Never do this outside a test!
        self.view = ProfileUpdateView()
        # Generate a fake request
        request = self.factory.get('/fake-url')
        # Attach the user to the request
        request.user = self.user
        # Attach the request to the view
        self.view.request = request

    def test_get_success_url(self):
        # Expect: '/users/testuser/', as that is the default username for
        #   self.make_user()
        self.assertEqual(
            self.view.get_success_url(),
            '/u/testuser/'
        )

    def test_get_object(self):
        # Expect: self.user, as that is the request's user object
        self.assertEqual(
            self.view.get_object(),
            self.user.profile
        )


class TestProfileDetailView(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin_user = AdminUserFactory()
        cls.user = UserFactory()

    def _get_request_view_and_content(self, create_content=True):
        request = self.client.get("/")
        request.user = self.user
        profile = request.user.profile
        profile.visibility = Visibility.PUBLIC
        profile.save()
        contents = []
        if create_content:
            contents.extend([
                ContentFactory(author=profile, order=3, pinned=True),
                ContentFactory(author=profile, order=2, pinned=True),
                ContentFactory(author=profile, order=1, pinned=True),
            ])
            Content.objects.filter(id=contents[0].id).update(order=3)
            Content.objects.filter(id=contents[1].id).update(order=2)
            Content.objects.filter(id=contents[2].id).update(order=1)
        view = ProfileDetailView(request=request, kwargs={"guid": profile.guid})
        view.object = profile
        view.target_profile = profile
        return request, view, contents, profile

    def test_get_context_data_contains_content_objects(self):
        request, view, contents, profile = self._get_request_view_and_content()
        view.content_list = view._get_contents_queryset()
        context = view.get_context_data()
        assert context["content_list"].count() == 3
        context_objs = {content for content in context["content_list"]}
        objs = set(contents)
        assert context_objs == objs

    def test_get_context_data_does_not_contain_content_for_other_users(self):
        request, view, contents, profile = self._get_request_view_and_content(create_content=False)
        user = UserFactory()
        ContentFactory(author=user.profile, pinned=True)
        user = UserFactory()
        ContentFactory(author=user.profile, pinned=True)
        view.content_list = view._get_contents_queryset()
        context = view.get_context_data()
        assert len(context["content_list"]) == 0

    def test_detail_view_renders(self):
        request, view, contents, profile = self._get_request_view_and_content()
        with self.login(username=self.admin_user.username):
            response = self.client.get(profile.get_absolute_url())
        assert response.status_code == 200

    def test_detail_view_has_no_organize_content_button_if_no_content(self):
        request = self.client.get("/")
        request.user = self.admin_user
        admin_profile = self.admin_user.profile
        Profile.objects.filter(id=admin_profile.id).update(visibility=Visibility.PUBLIC)
        with self.login(username=self.admin_user.username):
            response = self.client.get(admin_profile.get_absolute_url())
        assert str(response.content).find("Organize profile content") == -1
        ContentFactory(author=admin_profile, pinned=True)
        with self.login(username=self.admin_user.username):
            response = self.client.get(admin_profile.get_absolute_url())
        assert str(response.content).find("Organize profile content") > -1

    def test_contents_queryset_returns_public_only_for_unauthenticated(self):
        request, view, contents, profile = self._get_request_view_and_content(create_content=False)
        ContentFactory(author=profile, visibility=Visibility.SITE, pinned=True)
        ContentFactory(author=profile, visibility=Visibility.SELF, pinned=True)
        ContentFactory(author=profile, visibility=Visibility.LIMITED, pinned=True)
        public = ContentFactory(author=profile, visibility=Visibility.PUBLIC, pinned=True)
        request.user = AnonymousUser()
        qs = view._get_contents_queryset()
        assert qs.count() == 1
        assert qs.first() == public

    def test_contents_queryset_returns_public_or_site_only_for_authenticated(self):
        request, view, contents, profile = self._get_request_view_and_content(create_content=False)
        site = ContentFactory(author=profile, visibility=Visibility.SITE, pinned=True)
        ContentFactory(author=profile, visibility=Visibility.SELF, pinned=True)
        ContentFactory(author=profile, visibility=Visibility.LIMITED, pinned=True)
        public = ContentFactory(author=profile, visibility=Visibility.PUBLIC, pinned=True)
        request.user = User.objects.get(username="admin")
        qs = view._get_contents_queryset()
        assert qs.count() == 2
        assert set(qs) == {public, site}

    def test_contents_queryset_returns_all_for_self(self):
        request, view, contents, profile = self._get_request_view_and_content(create_content=False)
        site = ContentFactory(author=profile, visibility=Visibility.SITE, pinned=True)
        selff = ContentFactory(author=profile, visibility=Visibility.SELF, pinned=True)
        limited = ContentFactory(author=profile, visibility=Visibility.LIMITED, pinned=True)
        public = ContentFactory(author=profile, visibility=Visibility.PUBLIC, pinned=True)
        qs = view._get_contents_queryset()
        assert qs.count() == 4
        assert set(qs) == {public, site, selff, limited}

    def test_contents_queryset_returns_content_in_correct_order(self):
        request, view, contents, profile = self._get_request_view_and_content()
        qs = view._get_contents_queryset()
        assert qs[0].id == contents[2].id
        assert qs[1].id == contents[1].id
        assert qs[2].id == contents[0].id


@pytest.mark.usefixtures("admin_client", "rf")
class TestOrganizeContentUserDetailView:
    def _get_request_view_and_content(self, rf, create_content=True):
        request = rf.get("/")
        request.user = UserFactory()
        profile = request.user.profile
        profile.visibility = Visibility.PUBLIC
        profile.save()

        contents = []
        if create_content:
            contents.extend([
                ContentFactory(author=profile, order=3, pinned=True),
                ContentFactory(author=profile, order=2, pinned=True),
                ContentFactory(author=profile, order=1, pinned=True),
            ])
            Content.objects.filter(id=contents[0].id).update(order=3)
            Content.objects.filter(id=contents[1].id).update(order=2)
            Content.objects.filter(id=contents[2].id).update(order=1)
        view = OrganizeContentProfileDetailView(request=request)
        view.object = profile
        view.target_profile = profile
        view.kwargs = {"guid": profile.guid}
        return request, view, contents, profile

    def test_view_renders(self, admin_client, rf):
        response = admin_client.get(reverse("users:profile-organize"))
        assert response.status_code == 200

    def test_save_sort_order_updates_order(self, admin_client, rf):
        request, view, contents, profile = self._get_request_view_and_content(rf)
        qs = view._get_contents_queryset()
        assert qs[0].id == contents[2].id
        assert qs[1].id == contents[1].id
        assert qs[2].id == contents[0].id
        # Run id's via str() because request.POST gives them like that
        view._save_sort_order([str(contents[0].id), str(contents[1].id), str(contents[2].id)])
        qs = view._get_contents_queryset()
        assert qs[0].id == contents[0].id
        assert qs[1].id == contents[1].id
        assert qs[2].id == contents[2].id

    def test_save_sort_order_skips_non_qs_contents(self, admin_client, rf):
        request, view, contents, profile = self._get_request_view_and_content(rf)
        other_user = UserFactory()
        other_content = ContentFactory(author=other_user.profile, pinned=True)
        Content.objects.filter(id=other_content.id).update(order=100)
        view._save_sort_order([other_content.id])
        other_content.refresh_from_db()
        assert other_content.order == 100

    def test_get_success_url(self, admin_client, rf):
        request, view, contents, profile = self._get_request_view_and_content(rf)
        assert view.get_success_url() == "/"


@pytest.mark.usefixtures("admin_user", "client")
class TestProfileVisibilityForAnonymous:
    def test_visible_to_self_profile_requires_login_for_anonymous(self, admin_user, client):
        Profile.objects.filter(user__username=admin_user.username).update(visibility=Visibility.SELF)
        response = client.get("/u/admin/")
        assert response.status_code == 302
        response = client.get("/p/%s/" % admin_user.profile.guid)
        assert response.status_code == 302

    def test_visible_to_limited_profile_requires_login_for_anonymous(self, admin_user, client):
        Profile.objects.filter(user__username=admin_user.username).update(visibility=Visibility.LIMITED)
        response = client.get("/u/admin/")
        assert response.status_code == 302
        response = client.get("/p/%s/" % admin_user.profile.guid)
        assert response.status_code == 302

    def test_visible_to_site_profile_requires_login_for_anonymous(self, admin_user, client):
        Profile.objects.filter(user__username=admin_user.username).update(visibility=Visibility.SITE)
        response = client.get("/u/admin/")
        assert response.status_code == 302
        response = client.get("/p/%s/" % admin_user.profile.guid)
        assert response.status_code == 302

    def test_public_profile_doesnt_require_login(self, admin_user, client):
        Profile.objects.filter(user__username=admin_user.username).update(visibility=Visibility.PUBLIC)
        response = client.get("/u/admin/")
        assert response.status_code == 200
        response = client.get("/p/%s/" % admin_user.profile.guid)
        assert response.status_code == 200


@pytest.mark.usefixtures("admin_client")
class TestProfileVisibilityForLoggedInUsers:
    def test_visible_to_self_profile(self, admin_client):
        admin = User.objects.get(username="admin")
        Profile.objects.filter(user__username="admin").update(visibility=Visibility.SELF)
        user = UserFactory(username="foobar")
        Profile.objects.filter(user__username="foobar").update(visibility=Visibility.SELF)
        response = admin_client.get("/u/admin/")
        assert response.status_code == 200
        response = admin_client.get("/u/foobar/")
        assert response.status_code == 403
        response = admin_client.get("/p/%s/" % admin.profile.guid)
        assert response.status_code == 200
        response = admin_client.get("/p/%s/" % user.profile.guid)
        assert response.status_code == 403

    def test_visible_to_limited_profile(self, admin_client):
        admin = User.objects.get(username="admin")
        Profile.objects.filter(user__username="admin").update(visibility=Visibility.LIMITED)
        user = UserFactory(username="foobar")
        Profile.objects.filter(user__username="foobar").update(visibility=Visibility.LIMITED)
        response = admin_client.get("/u/admin/")
        assert response.status_code == 200
        response = admin_client.get("/u/foobar/")
        assert response.status_code == 403
        response = admin_client.get("/p/%s/" % admin.profile.guid)
        assert response.status_code == 200
        response = admin_client.get("/p/%s/" % user.profile.guid)
        assert response.status_code == 403

    def test_visible_to_site_profile(self, admin_client):
        admin = User.objects.get(username="admin")
        Profile.objects.filter(user__username="admin").update(visibility=Visibility.SITE)
        user = UserFactory(username="foobar")
        Profile.objects.filter(user__username="foobar").update(visibility=Visibility.SITE)
        response = admin_client.get("/u/admin/")
        assert response.status_code == 200
        response = admin_client.get("/u/foobar/")
        assert response.status_code == 200
        response = admin_client.get("/p/%s/" % admin.profile.guid)
        assert response.status_code == 200
        response = admin_client.get("/p/%s/" % user.profile.guid)
        assert response.status_code == 200

    def test_visible_to_public_profile(self, admin_client):
        admin = User.objects.get(username="admin")
        Profile.objects.filter(user__username="admin").update(visibility=Visibility.PUBLIC)
        user = UserFactory(username="foobar")
        Profile.objects.filter(user__username="foobar").update(visibility=Visibility.PUBLIC)
        response = admin_client.get("/u/admin/")
        assert response.status_code == 200
        response = admin_client.get("/u/foobar/")
        assert response.status_code == 200
        response = admin_client.get("/p/%s/" % admin.profile.guid)
        assert response.status_code == 200
        response = admin_client.get("/p/%s/" % user.profile.guid)
        assert response.status_code == 200


class TestUserAllContentView(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = UserFactory()
        Profile.objects.filter(user__username=cls.user.username).update(visibility=Visibility.PUBLIC)

    def test_all_content_view_renders_right_view(self):
        response = self.get("users:all-content", username=self.user.username)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data.get("view").__class__, ProfileAllContentView)
        self.assertEqual(response.context_data.get("object"), self.user.profile)


class TestProfileAllContentView(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = UserFactory()
        Profile.objects.filter(user__username=cls.user.username).update(visibility=Visibility.PUBLIC)
        cls.user_content = ContentFactory(author=cls.user.profile, visibility=Visibility.PUBLIC)
        cls.profile = ProfileFactory(visibility=Visibility.PUBLIC)
        cls.profile_content = ContentFactory(author=cls.profile, visibility=Visibility.PUBLIC)

    def test_renders_for_user(self):
        response = self.get("users:profile-all-content", guid=self.user.profile.guid)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context_data.get("pinned_content_exists"))
        ContentFactory(author=self.user.profile, pinned=True, visibility=Visibility.PUBLIC)
        response = self.get("users:profile-all-content", guid=self.user.profile.guid)
        self.assertTrue(response.context_data.get("pinned_content_exists"))
        self.assertEqual(response.context_data.get("stream_name"), "profile_all__%s" % self.user.profile.id)
        self.assertEqual(response.context_data.get("profile_stream_type"), "all_content")

    def test_renders_for_remote_profile(self):
        response = self.get("users:profile-all-content", guid=self.profile.guid)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context_data.get("pinned_content_exists"))
        self.assertEqual(response.context_data.get("stream_name"), "profile_all__%s" % self.profile.id)
        self.assertEqual(response.context_data.get("profile_stream_type"), "all_content")


class TestContactsFollowedView(SocialhomeTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = UserFactory()
        cls.profile = ProfileFactory()
        cls.user.profile.following.add(cls.profile)

    def test_login_required(self):
        # Not logged in, redirects to login
        self.get("users:contacts-followed")
        self.response_302()
        # Logged in
        with self.login(self.user):
            self.get("users:contacts-followed")
        self.response_200()

    def test_contains_table_object(self):
        with self.login(self.user):
            self.get("users:contacts-followed")
        self.assertTrue(isinstance(self.context["followed_table"], FollowedTable))
        self.assertContext("profile", self.user.profile)
