package xin.luoandlt.wxzy;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "SecureSession")
public class SecureSessionPlugin extends Plugin {
    @PluginMethod
    public void read(PluginCall call) {
        SecureSessionStore.SessionValue value = store().read();
        if (value == null) {
            call.resolve(new JSObject());
            return;
        }
        JSObject result = new JSObject();
        result.put("accessToken", value.accessToken);
        result.put("expiresAt", value.expiresAt);
        call.resolve(result);
    }

    @PluginMethod
    public void write(PluginCall call) {
        String accessToken = call.getString("accessToken");
        String expiresAt = call.getString("expiresAt");
        if (!SessionInput.isValid(accessToken, expiresAt)) {
            call.reject("accessToken and expiresAt are required");
            return;
        }
        try {
            store().write(accessToken, expiresAt);
            call.resolve();
        } catch (Exception exception) {
            call.reject("secure session write failed", exception);
        }
    }

    @PluginMethod
    public void clear(PluginCall call) {
        store().clear();
        call.resolve();
    }

    private SecureSessionStore store() {
        return new SecureSessionStore(getContext());
    }
}
