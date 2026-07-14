import AVFoundation
import SwiftUI

/// Renders the live preview and turns taps into device-space focus/exposure
/// points for `CameraController.focusAndExpose(at:)`
/// (docs/scannercam_spec.md §10.1: "Tapping the preview sets focus/exposure
/// point before locking"). Shows a brief reticle where the user tapped.
struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    var onTap: ((CGPoint) -> Void)?

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.videoPreviewLayer.session = session
        view.videoPreviewLayer.videoGravity = .resizeAspectFill

        let tapGesture = UITapGestureRecognizer(
            target: context.coordinator,
            action: #selector(Coordinator.handleTap(_:))
        )
        view.addGestureRecognizer(tapGesture)
        context.coordinator.previewView = view

        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        context.coordinator.onTap = onTap
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(onTap: onTap)
    }

    final class Coordinator: NSObject {
        var onTap: ((CGPoint) -> Void)?
        weak var previewView: PreviewView?

        init(onTap: ((CGPoint) -> Void)?) {
            self.onTap = onTap
        }

        @objc func handleTap(_ gesture: UITapGestureRecognizer) {
            guard let previewView, let onTap else { return }
            let location = gesture.location(in: previewView)
            previewView.showReticle(at: location)
            let devicePoint = previewView.videoPreviewLayer.captureDevicePointConverted(fromLayerPoint: location)
            onTap(devicePoint)
        }
    }

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

        var videoPreviewLayer: AVCaptureVideoPreviewLayer {
            // swiftlint:disable:next force_cast
            layer as! AVCaptureVideoPreviewLayer
        }

        private let reticle: CAShapeLayer = {
            let shape = CAShapeLayer()
            shape.path = UIBezierPath(ovalIn: CGRect(x: -32, y: -32, width: 64, height: 64)).cgPath
            shape.strokeColor = UIColor.systemYellow.cgColor
            shape.fillColor = UIColor.clear.cgColor
            shape.lineWidth = 2
            shape.opacity = 0
            return shape
        }()

        override init(frame: CGRect) {
            super.init(frame: frame)
            layer.addSublayer(reticle)
        }

        required init?(coder: NSCoder) {
            super.init(coder: coder)
            layer.addSublayer(reticle)
        }

        func showReticle(at point: CGPoint) {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            reticle.position = point
            reticle.removeAnimation(forKey: "fade")
            reticle.opacity = 1
            CATransaction.commit()

            let fade = CABasicAnimation(keyPath: "opacity")
            fade.fromValue = 1
            fade.toValue = 0
            fade.duration = 0.6
            fade.beginTime = CACurrentMediaTime() + 0.4
            fade.fillMode = .forwards
            fade.isRemovedOnCompletion = false
            reticle.add(fade, forKey: "fade")
        }
    }
}
