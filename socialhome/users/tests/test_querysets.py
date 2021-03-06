from unittest.mock import Mock

from django.test import TestCase

from socialhome.enums import Visibility
from socialhome.users.models import Profile
from socialhome.users.tests.factories import ProfileFactory


class TestProfileQuerySet(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.public_profile = ProfileFactory(visibility=Visibility.PUBLIC)
        cls.site_profile = ProfileFactory(visibility=Visibility.SITE)
        cls.profile = ProfileFactory()
        cls.profile2 = ProfileFactory()
        cls.public_profile.following.add(cls.site_profile, cls.profile)

    def test_visible_for_user_unauthenticated_user(self):
        self.assertEqual(set(Profile.objects.visible_for_user(Mock(is_authenticated=False))), {self.public_profile})

    def test_visible_for_user_authenticated_user(self):
        self.assertEqual(
            set(Profile.objects.visible_for_user(
                Mock(is_authenticated=True, profile=Mock(id=self.profile.id), is_staff=False)
            )),
            {self.public_profile, self.site_profile, self.profile}
        )

    def test_visible_for_user_staff_user(self):
        self.assertEqual(
            set(Profile.objects.visible_for_user(
                Mock(is_authenticated=True, is_staff=True)
            )),
            {self.public_profile, self.site_profile, self.profile, self.profile2}
        )

    def test_followers(self):
        self.assertEqual(list(Profile.objects.followers(self.public_profile)), [])
        self.assertEqual(list(Profile.objects.followers(self.site_profile)), [self.public_profile])
        self.assertEqual(list(Profile.objects.followers(self.profile)), [self.public_profile])
        self.assertEqual(list(Profile.objects.followers(self.profile2)), [])
