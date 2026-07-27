package xin.luoandlt.wxzy;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class SessionInputTest {
    @Test
    public void sessionInputRequiresBothNonBlankValues() {
        assertTrue(SessionInput.isValid("token", "2099-01-01T00:00:00Z"));
        assertFalse(SessionInput.isValid("", "2099-01-01T00:00:00Z"));
        assertFalse(SessionInput.isValid("token", "  "));
        assertFalse(SessionInput.isValid(null, "2099-01-01T00:00:00Z"));
    }
}
