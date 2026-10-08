from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Like password-reset tokens, but invalidated once the email is verified or changed."""

    key_salt = 'accounts.tokens.EmailVerificationTokenGenerator'

    def _make_hash_value(self, user, timestamp):
        return f'{user.pk}{user.email}{user.email_verified}{timestamp}'


email_verification_token = EmailVerificationTokenGenerator()
