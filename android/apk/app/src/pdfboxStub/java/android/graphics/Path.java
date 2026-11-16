package android.graphics;

/**
 * Layoutlib's Path constructor calls a native init that unit tests never load.
 * PdfBox text extraction only builds clipping paths, so a pure-Java stand-in is enough.
 * Paparazzi renders through layoutlib's own class loader, which still sees the real Path.
 */
public class Path {
    public Path() {}

    public Path(Path src) {}

    public void moveTo(float x, float y) {}

    public void lineTo(float x, float y) {}

    public void rLineTo(float dx, float dy) {}

    public void quadTo(float x1, float y1, float x2, float y2) {}

    public void cubicTo(float x1, float y1, float x2, float y2, float x3, float y3) {}

    public void close() {}

    public void reset() {}

    public void rewind() {}

    public void set(Path src) {}

    public void addRect(float left, float top, float right, float bottom, Direction dir) {}

    public boolean op(Path path, Op op) { return true; }

    public boolean isEmpty() { return false; }

    public FillType getFillType() { return FillType.WINDING; }

    public void setFillType(FillType fillType) {}

    public enum Op { DIFFERENCE, INTERSECT, UNION, XOR, REVERSE_DIFFERENCE }

    public enum Direction { CW, CCW }

    public enum FillType {
        WINDING(0),
        EVEN_ODD(1),
        INVERSE_WINDING(2),
        INVERSE_EVEN_ODD(3);

        public final int nativeInt;

        FillType(int nativeInt) { this.nativeInt = nativeInt; }
    }
}
