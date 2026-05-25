from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework import status

User = get_user_model()

class UserModelRoleSyncTests(APITestCase):
    def test_superuser_is_superuser_sync(self):
        """is_superuser=True forces role='SUPERUSER' and is_staff=True"""
        user = User.objects.create_user(
            username='su1',
            email='su1@example.com',
            password='password123',
            is_superuser=True
        )
        self.assertEqual(user.role, User.Role.SUPERUSER)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)

    def test_role_superuser_sync(self):
        """role='SUPERUSER' forces is_superuser=True and is_staff=True"""
        user = User.objects.create_user(
            username='su2',
            email='su2@example.com',
            password='password123',
            role=User.Role.SUPERUSER
        )
        self.assertEqual(user.role, User.Role.SUPERUSER)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)

    def test_role_admin_sync(self):
        """role='ADMIN' forces is_staff=True but is_superuser=False"""
        user = User.objects.create_user(
            username='admin1',
            email='admin1@example.com',
            password='password123',
            role=User.Role.ADMIN
        )
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_staff)


class UserViewSetRBACSecurityTests(APITestCase):
    def setUp(self):
        self.superuser = User.objects.create_user(
            username='super_owner',
            password='password123',
            role=User.Role.SUPERUSER
        )
        self.admin = User.objects.create_user(
            username='platform_operator',
            password='password123',
            role=User.Role.ADMIN
        )
        self.seller = User.objects.create_user(
            username='seller_user',
            password='password123',
            role=User.Role.SELLER
        )
        self.customer = User.objects.create_user(
            username='customer_user',
            password='password123',
            role=User.Role.CUSTOMER
        )

    def test_admin_cannot_promote_to_admin(self):
        """A regular ADMIN cannot promote a user to ADMIN"""
        self.client.force_authenticate(user=self.admin)
        url = f'/api/users/{self.seller.id}/'
        response = self.client.patch(url, {'role': 'ADMIN'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('role', response.data)

    def test_admin_cannot_promote_to_superuser(self):
        """A regular ADMIN cannot promote a user to SUPERUSER"""
        self.client.force_authenticate(user=self.admin)
        url = f'/api/users/{self.seller.id}/'
        response = self.client.patch(url, {'role': 'SUPERUSER'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('role', response.data)

    def test_admin_cannot_edit_superuser(self):
        """A regular ADMIN cannot edit a SUPERUSER account"""
        self.client.force_authenticate(user=self.admin)
        url = f'/api/users/{self.superuser.id}/'
        response = self.client.patch(url, {'phone_number': '123456'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('role', response.data)

    def test_admin_cannot_edit_peer_admin(self):
        """A regular ADMIN cannot edit another ADMIN account"""
        peer_admin = User.objects.create_user(
            username='peer_operator',
            password='password123',
            role=User.Role.ADMIN
        )
        self.client.force_authenticate(user=self.admin)
        url = f'/api/users/{peer_admin.id}/'
        response = self.client.patch(url, {'phone_number': '123456'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('role', response.data)

    def test_admin_cannot_create_admin_or_superuser(self):
        """A regular ADMIN cannot create a new ADMIN or SUPERUSER account"""
        self.client.force_authenticate(user=self.admin)
        url = '/api/users/'
        response = self.client.post(url, {
            'username': 'new_admin',
            'password': 'password123',
            'role': 'ADMIN',
            'first_name': 'New',
            'last_name': 'Admin',
            'email': 'newadmin@example.com',
            'phone_number': '0987654321',
            'accepted_liability_policy': True
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_superuser_can_promote_and_edit_all(self):
        """A SUPERUSER can perform all operations (promote/edit)"""
        self.client.force_authenticate(user=self.superuser)
        # Edit admin
        url_admin = f'/api/users/{self.admin.id}/'
        response = self.client.patch(url_admin, {'phone_number': '999999'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.phone_number, '999999')

        # Promote seller to ADMIN
        url_seller = f'/api/users/{self.seller.id}/'
        response = self.client.patch(url_seller, {'role': 'ADMIN'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.seller.refresh_from_db()
        self.assertEqual(self.seller.role, 'ADMIN')

    def test_admin_cannot_delete_superuser(self):
        """A regular ADMIN cannot delete a SUPERUSER account"""
        self.client.force_authenticate(user=self.admin)
        url = f'/api/users/{self.superuser.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(User.objects.filter(id=self.superuser.id).exists())

    def test_superuser_can_delete_superuser(self):
        """A SUPERUSER can delete a SUPERUSER account"""
        peer_superuser = User.objects.create_user(
            username='peer_superuser',
            password='password123',
            role=User.Role.SUPERUSER
        )
        self.client.force_authenticate(user=self.superuser)
        url = f'/api/users/{peer_superuser.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(id=peer_superuser.id).exists())


from django.contrib.admin.sites import AdminSite
from users.admin import CustomUserAdmin

class CustomUserAdminTests(APITestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin_class = CustomUserAdmin(User, self.site)
        self.superuser = User.objects.create_user(
            username='super_owner_admin',
            password='password123',
            role=User.Role.SUPERUSER
        )
        self.admin = User.objects.create_user(
            username='platform_operator_admin',
            password='password123',
            role=User.Role.ADMIN
        )
        self.seller = User.objects.create_user(
            username='seller_user_admin',
            password='password123',
            role=User.Role.SELLER
        )

    def test_get_readonly_fields_regular_admin(self):
        """Regular admin has restricted fields as read-only"""
        request = self.client.request().wsgi_request
        request.user = self.admin
        readonly = self.admin_class.get_readonly_fields(request, self.seller)
        for field in ('role', 'is_superuser', 'is_staff', 'user_permissions', 'groups'):
            self.assertIn(field, readonly)

    def test_get_readonly_fields_superuser(self):
        """Superuser does not have restricted fields as read-only"""
        request = self.client.request().wsgi_request
        request.user = self.superuser
        readonly = self.admin_class.get_readonly_fields(request, self.seller)
        self.assertEqual(len(readonly), 0)

    def test_has_change_permission_regular_admin(self):
        """Regular admin cannot change SUPERUSER or other ADMINs"""
        request = self.client.request().wsgi_request
        request.user = self.admin
        import unittest.mock as mock
        with mock.patch.object(User, 'has_perm', return_value=True):
            # Can change seller
            self.assertTrue(self.admin_class.has_change_permission(request, self.seller))
            # Cannot change superuser
            self.assertFalse(self.admin_class.has_change_permission(request, self.superuser))
            # Cannot change self or other admin
            self.assertFalse(self.admin_class.has_change_permission(request, self.admin))


    def test_has_change_permission_superuser(self):
        """Superuser can change anyone"""
        request = self.client.request().wsgi_request
        request.user = self.superuser
        self.assertTrue(self.admin_class.has_change_permission(request, self.seller))
        self.assertTrue(self.admin_class.has_change_permission(request, self.superuser))
        self.assertTrue(self.admin_class.has_change_permission(request, self.admin))


class CustomerSelfProfileUpdateTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='cust_test',
            password='password123',
            role=User.Role.CUSTOMER
        )
        self.seller = User.objects.create_user(
            username='sell_test',
            password='password123',
            role=User.Role.SELLER
        )

    def test_customer_can_update_own_basic_info(self):
        """Customer can update their first name, last name, email, and phone number"""
        self.client.force_authenticate(user=self.customer)
        url = '/api/auth/users/me/'
        
        payload = {
            'first_name': 'NewFirst',
            'last_name': 'NewLast',
            'email': 'newemail@example.com',
            'phone_number': '+255711111111'
        }
        response = self.client.patch(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, 'NewFirst')
        self.assertEqual(self.customer.last_name, 'NewLast')
        self.assertEqual(self.customer.email, 'newemail@example.com')
        self.assertEqual(self.customer.phone_number, '+255711111111')

    def test_customer_cannot_update_own_role(self):
        """Customer is blocked from updating their own role"""
        self.client.force_authenticate(user=self.customer)
        url = '/api/auth/users/me/'
        
        response = self.client.patch(url, {'role': 'ADMIN'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('role', response.data)

    def test_customer_cannot_update_own_employed_store(self):
        """Customer is blocked from updating their own employed_store"""
        from stores.models import Store
        store = Store.objects.create(name='Test Store', store_type='SHOP', owner=self.seller)
        
        self.client.force_authenticate(user=self.customer)
        url = '/api/auth/users/me/'
        
        response = self.client.patch(url, {'employed_store': store.id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('employed_store', response.data)

