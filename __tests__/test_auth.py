# scripts/test_auth.py
# Verifies JWKS endpoint is reachable + RS256 verification works
# Uses a real token from Supabase — sign up a test user first

import sys
sys.path.insert(0, "lambdas")

from load_env import *
from shared_lambda.secrets import get_secret
from shared_lambda.auth import verify_supabase_jwt, _get_jwks_client

def test_auth():
    print("\n=== Testing JWT Auth (RS256) ===")

    try:
        # Test 1: JWKS endpoint reachable
        import requests
        supabase_url = get_secret("SUPABASE_URL")
        jwks_url     = f"{supabase_url}/auth/v1/.well-known/jwks.json"

        response = requests.get(jwks_url, timeout=10)
        assert response.status_code == 200, \
            f"JWKS endpoint returned {response.status_code}"

        jwks = response.json()
        assert "keys" in jwks, "No 'keys' in JWKS response"
        assert len(jwks["keys"]) > 0, "JWKS has no keys"

        print(f"✅ JWKS endpoint reachable: {jwks_url}")
        print(f"✅ {len(jwks['keys'])} signing key(s) found")

        # Test 2: PyJWKClient initialises
        client = _get_jwks_client()
        print("✅ PyJWKClient initialised successfully")

        # Test 3: Verify a real token
        # CONCEPT: You need an actual Supabase JWT to test this.
        # Get one by signing in via the Supabase dashboard:
        # Authentication → Users → Create a test user
        # Then call: POST {SUPABASE_URL}/auth/v1/token?grant_type=password
        # with {"email": "test@test.com", "password": "testpassword"}
        # Copy the access_token from the response.
        print("\n--- Manual token test ---")
        print("To test token verification, paste a real Supabase JWT:")
        print("1. Go to Supabase Dashboard → Authentication → Users")
        print("2. Create test user: test@example.com / Test1234!")
        print("3. Run this curl command:")
        print(f"""
curl -X POST '{supabase_url}/auth/v1/token?grant_type=password' \\
  -H 'apikey: {get_secret("SUPABASE_ANON_KEY")[:20]}...' \\
  -H 'Content-Type: application/json' \\
  -d '{{"email":"test@example.com","password":"Test1234!"}}'
""")
        print("4. Copy the access_token value")
        print("5. Paste below (or press Enter to skip):")

        token = input("JWT token (or Enter to skip): ").strip()

        if token:
            payload = verify_supabase_jwt(token)
            print(f"✅ Token verified successfully")
            print(f"   user_id: {payload['sub']}")
            print(f"   email:   {payload.get('email')}")
            print(f"   role:    {payload.get('role')}")
        else:
            print("⏭  Token verification skipped")

        print("\n✅ Auth setup correct")

    except Exception as e:
        print(f"❌ Auth test failed: {e}")
        print("\nCheck:")
        print("  1. SUPABASE_URL correct?")
        print("  2. Signing Keys enabled in Supabase Auth settings?")
        print("  3. cryptography package installed?")

if __name__ == "__main__":
    test_auth()