package xin.luoandlt.wxzy;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class SecureSessionStore {
    static final String PREFS_NAME = "wenxi_secure_session";
    static final String PREFS_PAYLOAD = "payload";
    private static final String KEY_ALIAS = "wenxi.session.v1";
    private static final int GCM_IV_BYTES = 12;
    private static final int GCM_TAG_BITS = 128;

    private final SharedPreferences preferences;

    SecureSessionStore(Context context) {
        preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    SessionValue read() {
        String encoded = preferences.getString(PREFS_PAYLOAD, null);
        if (encoded == null) return null;
        try {
            JSONObject payload = new JSONObject(decrypt(encoded));
            String accessToken = payload.getString("accessToken");
            String expiresAt = payload.getString("expiresAt");
            if (!SessionInput.isValid(accessToken, expiresAt)) throw new IllegalArgumentException("invalid session payload");
            return new SessionValue(accessToken, expiresAt);
        } catch (Exception exception) {
            clear();
            return null;
        }
    }

    void write(String accessToken, String expiresAt) throws Exception {
        if (!SessionInput.isValid(accessToken, expiresAt)) throw new IllegalArgumentException("accessToken and expiresAt are required");
        JSONObject payload = new JSONObject();
        payload.put("accessToken", accessToken);
        payload.put("expiresAt", expiresAt);
        if (!preferences.edit().putString(PREFS_PAYLOAD, encrypt(payload.toString())).commit()) {
            throw new IllegalStateException("secure session persistence failed");
        }
    }

    void clear() {
        preferences.edit().remove(PREFS_PAYLOAD).commit();
    }

    String rawPayload() {
        return preferences.getString(PREFS_PAYLOAD, null);
    }

    private String encrypt(String plaintext) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
        byte[] ciphertext = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
        byte[] iv = cipher.getIV();
        byte[] combined = new byte[iv.length + ciphertext.length];
        System.arraycopy(iv, 0, combined, 0, iv.length);
        System.arraycopy(ciphertext, 0, combined, iv.length, ciphertext.length);
        return Base64.encodeToString(combined, Base64.NO_WRAP);
    }

    private String decrypt(String encoded) throws Exception {
        byte[] combined = Base64.decode(encoded, Base64.NO_WRAP);
        if (combined.length <= GCM_IV_BYTES) throw new IllegalArgumentException("invalid encrypted payload");
        byte[] iv = new byte[GCM_IV_BYTES];
        byte[] ciphertext = new byte[combined.length - iv.length];
        System.arraycopy(combined, 0, iv, 0, iv.length);
        System.arraycopy(combined, iv.length, ciphertext, 0, ciphertext.length);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), new GCMParameterSpec(GCM_TAG_BITS, iv));
        return new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
    }

    private SecretKey getOrCreateKey() throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        SecretKey existing = (SecretKey) keyStore.getKey(KEY_ALIAS, null);
        if (existing != null) return existing;
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build());
        return generator.generateKey();
    }

    static final class SessionValue {
        final String accessToken;
        final String expiresAt;

        SessionValue(String accessToken, String expiresAt) {
            this.accessToken = accessToken;
            this.expiresAt = expiresAt;
        }
    }
}
