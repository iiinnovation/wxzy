package xin.luoandlt.wxzy;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class SecureSessionStoreInstrumentedTest {
    @Test
    public void secureSessionPersistsEncryptedAndClears() throws Exception {
        Context appContext = InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals("xin.luoandlt.wxzy", appContext.getPackageName());
        SecureSessionStore store = new SecureSessionStore(appContext);
        store.clear();
        String token = "instrumentation-session-token-that-must-not-be-plaintext";
        String expiresAt = "2099-01-01T00:00:00Z";

        store.write(token, expiresAt);
        SecureSessionStore.SessionValue restored = new SecureSessionStore(appContext).read();
        assertNotNull(restored);
        assertEquals(token, restored.accessToken);
        assertEquals(expiresAt, restored.expiresAt);
        assertNotNull(store.rawPayload());
        assertFalse(store.rawPayload().contains(token));

        store.clear();
        assertNull(store.read());
    }
}
