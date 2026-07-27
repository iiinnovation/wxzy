package xin.luoandlt.wxzy;

final class SessionInput {
    private SessionInput() {}

    static boolean isValid(String accessToken, String expiresAt) {
        return accessToken != null && !accessToken.isBlank()
                && expiresAt != null && !expiresAt.isBlank();
    }
}
